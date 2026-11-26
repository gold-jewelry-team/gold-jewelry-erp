"""Sales draft pricing and inventory completion services."""
from datetime import datetime, timezone
from decimal import Decimal, ROUND_FLOOR
from uuid import UUID, uuid4

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.customer_order import CustomerOrder
from app.models.payment_transaction import PaymentTransaction
from app.models.product import Product
from app.models.sale import Sale, SaleLine
from app.models.site import Site
from app.models.storage_location import StorageLocation
from app.services.inventory import create_inventory_movement
from app.services.daily_closing import assert_business_day_open
from app.services.pricing.gold_prices import get_effective_gold_price
from app.services.pricing.rounding import round_twd_like_legacy
from app.services.pricing.sales import SalePricingInput, calculate_sale_amount

PRICING_RULE_VERSION = "legacy-v1"
CARD_FEE_RATE = Decimal("0.05")


_GOLD_UNIT_GRAMS = {"QIAN": Decimal("3.75"), "GRAM": Decimal("1"), "TAEL": Decimal("37.5")}


def _convert_gold_price(value: Decimal, from_unit: str, to_unit: str) -> Decimal:
    """Convert a price quoted per source unit to a price per target unit."""
    from_grams = _GOLD_UNIT_GRAMS.get(from_unit)
    to_grams = _GOLD_UNIT_GRAMS.get(to_unit)
    if from_grams is None or to_grams is None:
        raise ValueError("商品重量單位無法換算，請確認金價與商品單位設定。")
    return value * to_grams / from_grams


def _allocate_integer_total(total: Decimal, weights: list[Decimal]) -> list[Decimal]:
    """Allocate a whole-TWD total proportionally using largest remainders.

    Signed weights are supported. The returned integer amounts always sum to
    the requested total, so line-level settlement snapshots reconcile exactly.
    """
    if not weights:
        return []
    raw_sum = sum(weights, Decimal("0"))
    if raw_sum == 0:
        if total != 0:
            raise ValueError("無法將付款金額分攤至金額合計為零的商品。")
        return [Decimal("0") for _ in weights]

    raw = [total * weight / raw_sum for weight in weights]
    floors = [value.to_integral_value(rounding=ROUND_FLOOR) for value in raw]
    remainder = int(total - sum(floors, Decimal("0")))
    fractions = [value - floor for value, floor in zip(raw, floors)]

    if remainder > 0:
        order = sorted(range(len(weights)), key=lambda i: (fractions[i], -i), reverse=True)
        for i in order[:remainder]:
            floors[i] += 1
    elif remainder < 0:
        order = sorted(range(len(weights)), key=lambda i: (fractions[i], i))
        for i in order[:abs(remainder)]:
            floors[i] -= 1
    return floors


def _customer_order_payment_nets(session: Session, order_id: UUID) -> dict[str, Decimal]:
    rows = session.execute(
        select(
            PaymentTransaction.payment_method,
            PaymentTransaction.direction,
            func.coalesce(func.sum(PaymentTransaction.amount), 0),
        )
        .where(PaymentTransaction.customer_order_id == order_id)
        .group_by(PaymentTransaction.payment_method, PaymentTransaction.direction)
    ).all()
    balances: dict[str, Decimal] = {}
    for method, direction, amount in rows:
        signed = Decimal(amount or 0) if direction == "IN" else -Decimal(amount or 0)
        balances[method] = balances.get(method, Decimal("0")) + signed
    return balances


def _validate_customer_order_lines(order: CustomerOrder, sale_lines: list[SaleLine]) -> None:
    items = order.items if isinstance(order.items, list) else []
    if len(items) != len(sale_lines):
        raise ValueError("正式銷售品項數量必須與客訂明細一致，請勿遺漏或額外加入商品。")
    for index, (item, line) in enumerate(zip(items, sale_lines), start=1):
        stored_product_id = item.get("product_id")
        line_product_id = str(line.product_id) if line.product_id is not None else None
        expected_product_id = str(stored_product_id) if stored_product_id else None
        if expected_product_id != line_product_id:
            raise ValueError(f"第 {index} 項正式商品與客訂明細不一致，請重新核對。")
        if line.product_id is None:
            stored_name = (item.get("product_name") or "").strip()
            if stored_name and stored_name != line.product_name_snapshot:
                raise ValueError(f"第 {index} 項臨時估價商品名稱與客訂明細不一致。")
        stored_old_weight = Decimal(str(item.get("old_gold_weight") or "0"))
        if stored_old_weight != Decimal(str(line.old_gold_weight or "0")):
            raise ValueError(f"第 {index} 項舊金折抵重量與客訂明細不一致。")
        if item.get("trade_in_source") != line.trade_in_source:
            raise ValueError(f"第 {index} 項舊金來源與客訂明細不一致。")


def create_sale_draft(
    session: Session,
    *,
    company_id: UUID,
    site_id: UUID,
    sale_no: str,
    payment_method: str,
    lines: list[dict],
    card_amount: Decimal | None = None,
    note: str | None = None,
    at: datetime | None = None,
    customer_order_id: UUID | None = None,
) -> Sale:
    """Create a draft sale; linked customer-order receipts remain in their original ledger."""
    if payment_method not in {"CASH", "CARD", "MIXED", "TRANSFER", "OTHER"}:
        raise ValueError("不支援的付款方式。")
    site = session.get(Site, site_id)
    if site is None or site.company_id != company_id:
        raise ValueError("據點不存在或不屬於指定公司。")
    linked_order = None
    if customer_order_id is not None:
        linked_order = session.execute(
            select(CustomerOrder).where(
                CustomerOrder.id == customer_order_id,
                CustomerOrder.company_id == company_id,
            ).with_for_update()
        ).scalar_one_or_none()
        if linked_order is None:
            raise ValueError("找不到指定客訂單，或客訂單不屬於目前公司。")
        if linked_order.site_id != site_id:
            raise ValueError("客訂單與正式銷售必須屬於同一營業據點。")
        if linked_order.status != "READY":
            raise ValueError("只有已到貨且待交貨的客訂單可以建立正式銷售。")
        existing_sale = session.scalar(
            select(Sale.id).where(Sale.customer_order_id == linked_order.id)
        )
        if existing_sale is not None:
            raise ValueError("此客訂單已建立正式銷售草稿，請開啟原銷售單繼續處理。")
    if not lines:
        raise ValueError("銷售明細不可空白。")

    priced_at = at or datetime.now(timezone.utc)
    assert_business_day_open(session, site_id=site_id, at=priced_at)
    sale = Sale(
        company_id=company_id,
        site_id=site_id,
        customer_order_id=linked_order.id if linked_order is not None else None,
        sale_no=sale_no,
        payment_method=payment_method,
        currency_code="TWD",
        subtotal=Decimal("0"),
        card_amount=Decimal("0"),
        card_fee=Decimal("0"),
        final_amount=Decimal("0"),
        note=note,
    )
    session.add(sale)
    session.flush()

    line_results: list[tuple[SaleLine, Decimal]] = []
    subtotal_total = Decimal("0")

    for line_no, item in enumerate(lines, start=1):
        product_id = item.get("product_id")
        product = None
        location = None
        if product_id is not None:
            product = session.execute(
                select(Product).where(
                    Product.id == product_id,
                    Product.company_id == company_id,
                ).with_for_update()
            ).scalar_one_or_none()
            if product is None or not product.is_active:
                raise ValueError("商品不存在、不屬於指定公司或已停用。")
            location = session.get(StorageLocation, item.get("source_location_id"))
            if location is None or location.site_id != site_id or not location.is_active:
                raise ValueError("出貨儲存位置不存在、未啟用或不屬於銷售據點。")
            weight = item.get("net_weight") or product.net_weight
            gross_weight = product.gross_weight
            weight_unit_code = product.weight_unit_code
            labor = item.get("labor_fee")
            if labor is None:
                labor = product.labor_fee
            product_code_snapshot = product.product_code
            barcode_snapshot = product.barcode
            product_name_snapshot = product.name
        else:
            # Temporary estimate: persist the exact sold description and weight,
            # but do not associate it with inventory or a storage location.
            product_name_snapshot = (item.get("product_name") or "").strip()
            if not product_name_snapshot:
                raise ValueError("臨時估價成交必須提供商品名稱。")
            weight = item.get("net_weight")
            weight_unit_code = item.get("weight_unit_code")
            if weight is None or weight <= 0 or weight_unit_code not in _GOLD_UNIT_GRAMS:
                raise ValueError("臨時估價成交必須提供有效重量及重量單位。")
            gross_weight = item.get("gross_weight") or weight
            labor = item.get("labor_fee")
            if labor is None:
                labor = Decimal("0")
            product_code_snapshot = item.get("product_code") or "臨時估價"
            barcode_snapshot = item.get("barcode")

        sell_price = get_effective_gold_price(
            session, company_id=company_id, site_id=site_id, price_type="SELL", at=priced_at
        )
        buy_price = get_effective_gold_price(
            session, company_id=company_id, site_id=site_id, price_type="BUY", at=priced_at
        )
        if sell_price is None or buy_price is None:
            raise ValueError("找不到交易時間有效的買入或賣出金價，請先建立金價。")
        if sell_price.currency_code != "TWD" or buy_price.currency_code != "TWD":
            raise ValueError("目前銷售計價僅支援 TWD 金價。")
        sell_rate = _convert_gold_price(sell_price.price_value, sell_price.unit_code, weight_unit_code)
        buy_rate = _convert_gold_price(buy_price.price_value, buy_price.unit_code, weight_unit_code)

        old_weight = item.get("old_gold_weight", Decimal("0"))
        has_trade_in = old_weight > 0
        trade_in_source = item.get("trade_in_source") if has_trade_in else None
        ratio = item.get("trade_in_ratio", Decimal("0.95"))

        result = calculate_sale_amount(SalePricingInput(
            new_weight=weight,
            sell_gold_price=sell_rate,
            buy_gold_price=buy_rate,
            labor_fee=labor,
            has_trade_in=has_trade_in,
            trade_in_source=trade_in_source,
            old_weight=old_weight,
            trade_in_ratio=ratio,
            is_credit_card=False,
        ))

        line = SaleLine(
            sale_id=sale.id,
            line_no=line_no,
            product_id=product.id if product else None,
            source_location_id=location.id if location else None,
            product_code_snapshot=product_code_snapshot,
            barcode_snapshot=barcode_snapshot,
            product_name_snapshot=product_name_snapshot,
            gross_weight=gross_weight,
            net_weight=weight,
            weight_unit_code=weight_unit_code,
            labor_fee=labor,
            sell_gold_price_id=sell_price.id,
            sell_gold_price_value=sell_price.price_value,
            sell_gold_price_unit_code=sell_price.unit_code,
            buy_gold_price_id=buy_price.id,
            buy_gold_price_value=buy_price.price_value,
            buy_gold_price_unit_code=buy_price.unit_code,
            price_currency_code="TWD",
            price_effective_at=max(sell_price.effective_at, buy_price.effective_at),
            trade_in_source=trade_in_source,
            old_gold_weight=old_weight if has_trade_in else Decimal("0"),
            trade_in_ratio=(Decimal("1") if trade_in_source == "LOCAL" else ratio) if has_trade_in else None,
            adjusted_old_gold_weight=result.adjusted_old_weight,
            pricing_rule_version=PRICING_RULE_VERSION,
            subtotal=result.subtotal,
            card_fee=Decimal("0"),
            final_amount=Decimal("0"),
        )
        session.add(line)
        line_results.append((line, result.subtotal))
        subtotal_total += result.subtotal

    if linked_order is not None:
        _validate_customer_order_lines(linked_order, [line for line, _ in line_results])
        if card_amount is None:
            prior_card = max(
                Decimal("0"),
                _customer_order_payment_nets(session, linked_order.id).get("CARD", Decimal("0")),
            )
            card_amount = prior_card

    positive_subtotal = max(Decimal("0"), round_twd_like_legacy(subtotal_total))
    if linked_order is not None and card_amount is not None:
        # Older customer-order card receipts did not add the POS surcharge.
        # Treat their net amount as card principal, capped at today's positive
        # item subtotal; any excess remains refundable through the order ledger.
        card_amount = min(max(Decimal("0"), card_amount), positive_subtotal)
    if card_amount is None:
        if payment_method == "CARD":
            card_amount = positive_subtotal
        elif payment_method == "MIXED":
            raise ValueError("部分刷卡請輸入顧客指定的刷卡本金。")
        else:
            card_amount = Decimal("0")

    if card_amount < 0 or card_amount != card_amount.to_integral_value():
        raise ValueError("刷卡金額必須為非負整數元。")
    if card_amount > positive_subtotal:
        raise ValueError("刷卡本金不可超過商品原始總額。")
    if payment_method in {"TRANSFER", "OTHER"} and card_amount > 0:
        raise ValueError("轉帳或其他付款方式不可同時指定刷卡金額。")

    if card_amount > 0 and card_amount < positive_subtotal:
        normalized_method = "MIXED"
    elif card_amount > 0:
        normalized_method = "CARD"
    elif payment_method in {"TRANSFER", "OTHER"}:
        normalized_method = payment_method
    else:
        normalized_method = "CASH"

    # Allocate card principal only across positive-value lines.
    weights = [max(Decimal("0"), subtotal) for _, subtotal in line_results]
    if card_amount > 0 and sum(weights, Decimal("0")) <= 0:
        raise ValueError("此銷售單沒有可供刷卡分攤的正數商品金額。")
    card_allocations = (
        _allocate_integer_total(card_amount, weights) if card_amount > 0
        else [Decimal("0") for _ in line_results]
    )

    card_fee_total = round_twd_like_legacy(card_amount * CARD_FEE_RATE)
    fee_allocations = (
        _allocate_integer_total(card_fee_total, card_allocations)
        if card_fee_total > 0 else [Decimal("0") for _ in line_results]
    )

    final_total = round_twd_like_legacy(subtotal_total + card_fee_total)
    final_allocations = _allocate_integer_total(
        final_total,
        [subtotal + fee for (_, subtotal), fee in zip(line_results, fee_allocations)],
    )

    for (line, _), fee, final in zip(line_results, fee_allocations, final_allocations):
        line.card_fee = fee
        line.final_amount = final

    sale.payment_method = normalized_method
    sale.subtotal = subtotal_total
    sale.card_amount = card_amount
    sale.card_fee = card_fee_total
    sale.final_amount = final_total
    if linked_order is not None:
        linked_order.final_sale_amount = final_total
    session.flush()
    return sale



def update_sale_draft(
    session: Session, *, company_id: UUID, sale_id: UUID, sale_no: str,
    payment_method: str, lines: list[dict], card_amount: Decimal | None = None,
    note: str | None = None, at: datetime | None = None,
) -> Sale:
    """Reprice and replace all lines of an uncompleted sale without changing its identity."""
    sale = session.execute(
        select(Sale).where(Sale.id == sale_id, Sale.company_id == company_id).with_for_update()
    ).scalar_one_or_none()
    if sale is None:
        raise ValueError("找不到指定銷售單。")
    if sale.status != "DRAFT":
        raise ValueError("只有尚未完成的銷售草稿可以修改；已完成銷售請走退貨流程。")
    linked_order = None
    if sale.customer_order_id is not None:
        linked_order = session.execute(
            select(CustomerOrder).where(
                CustomerOrder.id == sale.customer_order_id,
                CustomerOrder.company_id == company_id,
            ).with_for_update()
        ).scalar_one_or_none()
        if linked_order is None or linked_order.status != "READY":
            raise ValueError("客訂連結已失效，請先核對客訂單狀態。")
    if not lines:
        raise ValueError("銷售明細不可空白。")

    if linked_order is not None:
        candidate_lines = [
            SaleLine(
                product_id=item.get("product_id"),
                product_name_snapshot=(item.get("product_name") or "").strip() or "臨時估價",
                old_gold_weight=Decimal(str(item.get("old_gold_weight") or "0")),
                trade_in_source=item.get("trade_in_source"),
            )
            for item in lines
        ]
        _validate_customer_order_lines(linked_order, candidate_lines)
    temporary = create_sale_draft(
        session, company_id=company_id, site_id=sale.site_id,
        sale_no="TMP-" + uuid4().hex[:24], payment_method=payment_method,
        lines=lines, card_amount=card_amount, note=note, at=at,
    )
    old_lines = list(session.scalars(
        select(SaleLine).where(SaleLine.sale_id == sale.id)
    ).all())
    for old_line in old_lines:
        session.delete(old_line)
    session.flush()

    for line in list(temporary.lines):
        line.sale = sale
    sale.sale_no = sale_no
    sale.payment_method = temporary.payment_method
    sale.currency_code = temporary.currency_code
    sale.subtotal = temporary.subtotal
    sale.card_amount = temporary.card_amount
    sale.card_fee = temporary.card_fee
    sale.final_amount = temporary.final_amount
    sale.note = note
    if linked_order is not None:
        linked_order.final_sale_amount = temporary.final_amount
    session.flush()
    session.delete(temporary)
    session.flush()
    return sale


def complete_sale(session: Session, *, company_id: UUID, sale_id: UUID) -> Sale:
    """Atomically deduct each sold item and complete the sale."""
    sale = session.execute(
        select(Sale).where(Sale.id == sale_id, Sale.company_id == company_id).with_for_update()
    ).scalar_one_or_none()
    if sale is None:
        raise ValueError("找不到指定銷售單。")
    # Completing a sale is safe to retry after a lost HTTP response: the
    # first request commits the stock ledger and status atomically, so a
    # repeated request should return the completed sale without posting stock
    # movements a second time.
    if sale.status == "COMPLETED":
        return sale
    if sale.status != "DRAFT":
        raise ValueError("只有草稿銷售單可以完成。")
    linked_order = None
    if sale.customer_order_id is not None:
        linked_order = session.execute(
            select(CustomerOrder).where(
                CustomerOrder.id == sale.customer_order_id,
                CustomerOrder.company_id == company_id,
            ).with_for_update()
        ).scalar_one_or_none()
        if linked_order is None:
            raise ValueError("正式銷售連結的客訂單不存在，請先核對資料。")
        if linked_order.status != "READY":
            raise ValueError("客訂單必須維持待交貨狀態，才能完成正式銷售。")
        if linked_order.final_sale_amount != sale.final_amount:
            raise ValueError("正式銷售金額快照已變動，請重新開啟銷售草稿核對。")
        if sale.final_amount > 0 and linked_order.deposit_amount != sale.final_amount:
            difference = sale.final_amount - linked_order.deposit_amount
            if difference > 0:
                raise ValueError(f"客訂尚有尾款 NT$ {difference} 未收清，不可完成交貨。")
            raise ValueError(f"客訂超收 NT$ {abs(difference)}，請先依原付款方式完成退款。")
        if sale.final_amount <= 0 and linked_order.deposit_amount != 0:
            raise ValueError("此筆正式銷售不需向客戶收款，請先退還客訂目前淨收款後再完成交貨。")
    lines = list(session.scalars(
        select(SaleLine).where(SaleLine.sale_id == sale.id).order_by(SaleLine.line_no)
    ).all())
    if not lines:
        raise ValueError("銷售單沒有商品明細。")

    completed_at = datetime.now(timezone.utc)
    assert_business_day_open(session, site_id=sale.site_id, at=completed_at)
    for line in lines:
        # Temporary estimate lines are sold as descriptive snapshots only and
        # intentionally do not create inventory movements.
        if line.product_id is None and line.source_location_id is None:
            continue
        if line.product_id is None or line.source_location_id is None:
            raise ValueError("銷售明細的商品與出貨儲存位置資料不完整。")
        create_inventory_movement(
            session,
            company_id=company_id,
            site_id=sale.site_id,
            product_id=line.product_id,
            movement_type="SALE",
            quantity=Decimal("1"),
            from_location_id=line.source_location_id,
            weight=line.net_weight,
            weight_unit_code=line.weight_unit_code,
            occurred_at=completed_at,
            reference_type="SALE_LINE",
            reference_id=line.id,
            note=f"銷售單 {sale.sale_no}",
        )
    sale.status = "COMPLETED"
    sale.completed_at = completed_at
    if linked_order is not None:
        linked_order.status = "COMPLETED"
    session.flush()
    return sale


def void_sale_draft(session: Session, *, company_id: UUID, sale_id: UUID) -> Sale:
    sale = session.execute(
        select(Sale).where(Sale.id == sale_id, Sale.company_id == company_id).with_for_update()
    ).scalar_one_or_none()
    if sale is None:
        raise ValueError("找不到指定銷售單。")
    if sale.status != "DRAFT":
        raise ValueError("只有草稿銷售單可以作廢；已完成銷售請走退貨流程。")
    if sale.customer_order_id is not None:
        linked_order = session.execute(
            select(CustomerOrder).where(
                CustomerOrder.id == sale.customer_order_id,
                CustomerOrder.company_id == company_id,
            ).with_for_update()
        ).scalar_one_or_none()
        if linked_order is None or linked_order.status != "READY":
            raise ValueError("客訂連結狀態異常，無法安全解除銷售草稿。")
        linked_order.final_sale_amount = None
        sale.customer_order_id = None
    sale.status = "VOID"
    sale.voided_at = datetime.now(timezone.utc)
    session.flush()
    return sale
