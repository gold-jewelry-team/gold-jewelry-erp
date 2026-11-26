"""Purchase order creation, lifecycle and atomic goods receiving."""
import base64
from datetime import date
from decimal import Decimal, ROUND_HALF_UP
from uuid import UUID

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.models.company import Company
from app.models.inventory import InventoryMovement
from app.models.product import Product
from app.models.purchase import Purchase, PurchaseLine
from app.models.site import Site
from app.models.storage_location import StorageLocation
from app.models.supplier import Supplier
from app.models.supplier_payable import SupplierBill


def create_purchase(session: Session, *, company_id: UUID, site_id: UUID, supplier_id: UUID,
                    purchase_no: str, order_date: date, expected_date: date | None,
                    currency_code: str, note: str | None, lines: list[dict]) -> Purchase:
    company = session.get(Company, company_id)
    site = session.get(Site, site_id)
    supplier = session.get(Supplier, supplier_id)
    if company is None:
        raise ValueError("找不到指定公司。")
    if site is None or site.company_id != company_id:
        raise ValueError("據點不存在或不屬於指定公司。")
    if supplier is None or supplier.company_id != company_id or not supplier.is_active:
        raise ValueError("供應商不存在、未啟用或不屬於指定公司。")
    if not lines:
        raise ValueError("採購單至少需要一筆商品明細。")
    if len(currency_code) != 3:
        raise ValueError("幣別必須使用三碼代碼。")

    product_ids = {item["product_id"] for item in lines}
    products = {p.id: p for p in session.scalars(select(Product).where(Product.id.in_(product_ids))).all()}
    if len(products) != len(product_ids):
        raise ValueError("部分商品不存在。")
    if any(p.company_id != company_id or not p.is_active for p in products.values()):
        raise ValueError("採購商品未啟用或不屬於指定公司。")

    purchase = Purchase(
        company_id=company_id, site_id=site_id, supplier_id=supplier_id,
        purchase_no=purchase_no, order_date=order_date, expected_date=expected_date,
        currency_code=currency_code.upper(), note=note, status="DRAFT",
    )
    session.add(purchase)
    session.flush()
    for item in lines:
        session.add(PurchaseLine(purchase_id=purchase.id, **item))
    session.flush()
    return purchase


def update_purchase(
    session: Session, *, company_id: UUID, purchase_id: UUID, site_id: UUID,
    supplier_id: UUID, purchase_no: str, order_date: date, expected_date: date | None,
    currency_code: str, note: str | None, lines: list[dict],
) -> Purchase:
    purchase = session.execute(select(Purchase).where(
        Purchase.id == purchase_id, Purchase.company_id == company_id
    ).with_for_update()).scalar_one_or_none()
    if purchase is None:
        raise ValueError("找不到指定採購單。")
    if purchase.status != "DRAFT":
        raise ValueError("只有草稿採購單可以修改。")
    if not lines:
        raise ValueError("採購單至少需要一筆商品明細。")
    if len(currency_code) != 3:
        raise ValueError("幣別必須使用三碼代碼。")
    linked_bill = session.scalar(select(SupplierBill.id).where(
        SupplierBill.purchase_id == purchase_id, SupplierBill.status != "VOID"
    ).limit(1))
    if linked_bill is not None:
        raise ValueError("採購單已有有效供應商帳單，請先處理帳款後再修改。")
    site = session.get(Site, site_id)
    if site is None or site.company_id != company_id:
        raise ValueError("據點不存在或不屬於指定公司。")
    if not site.is_active and site_id != purchase.site_id:
        raise ValueError("不可將草稿採購單移至停用中的據點。")
    supplier = session.get(Supplier, supplier_id)
    if supplier is None or supplier.company_id != company_id:
        raise ValueError("供應商不存在或不屬於指定公司。")
    if not supplier.is_active and supplier_id != purchase.supplier_id:
        raise ValueError("不可將草稿採購單改為停用中的供應商。")

    existing_product_ids = set(session.scalars(select(PurchaseLine.product_id).where(
        PurchaseLine.purchase_id == purchase_id
    )).all())
    product_ids = {item["product_id"] for item in lines}
    products = {p.id: p for p in session.scalars(select(Product).where(
        Product.id.in_(product_ids), Product.company_id == company_id
    )).all()}
    if len(products) != len(product_ids):
        raise ValueError("部分商品不存在或不屬於指定公司。")
    if any(not p.is_active and product_id not in existing_product_ids for product_id, p in products.items()):
        raise ValueError("不可新增停用中的商品至採購草稿。")

    purchase.site_id = site_id
    purchase.supplier_id = supplier_id
    purchase.purchase_no = purchase_no
    purchase.order_date = order_date
    purchase.expected_date = expected_date
    purchase.currency_code = currency_code.upper()
    purchase.note = note
    for old_line in list(purchase.lines):
        session.delete(old_line)
    session.flush()
    for item in lines:
        session.add(PurchaseLine(purchase_id=purchase.id, **item))
    session.flush()
    return purchase


def submit_purchase(session: Session, *, purchase_id: UUID) -> Purchase:
    purchase = session.execute(select(Purchase).where(Purchase.id == purchase_id).with_for_update()).scalar_one_or_none()
    if purchase is None:
        raise ValueError("找不到採購單。")
    # A retry may arrive after the original submit committed but its HTTP
    # response was lost. Receiving can also advance the status before that
    # retry arrives; all post-submit states therefore confirm the same action.
    if purchase.status in {"ORDERED", "PARTIALLY_RECEIVED", "RECEIVED"}:
        return purchase
    if purchase.status != "DRAFT":
        raise ValueError("只有草稿採購單可以送出。")
    if not session.scalar(select(PurchaseLine.id).where(PurchaseLine.purchase_id == purchase_id).limit(1)):
        raise ValueError("採購單沒有商品明細。")
    purchase.status = "ORDERED"
    session.flush()
    return purchase


def cancel_purchase(session: Session, *, purchase_id: UUID) -> Purchase:
    purchase = session.execute(select(Purchase).where(Purchase.id == purchase_id).with_for_update()).scalar_one_or_none()
    if purchase is None:
        raise ValueError("找不到採購單。")
    # Cancellation is a terminal state transition. Treat an exact retry
    # after a lost response as success without changing any related records.
    if purchase.status == "CANCELLED":
        return purchase
    if purchase.status not in {"DRAFT", "ORDERED"}:
        raise ValueError("只有草稿或尚未收貨的採購單可以取消。")
    linked_bill_id = session.scalar(
        select(SupplierBill.id).where(
            SupplierBill.purchase_id == purchase_id,
            SupplierBill.status != "VOID",
        ).limit(1)
    )
    if linked_bill_id is not None:
        raise ValueError("採購單已有有效供應商帳單，請先處理帳款後再取消。")
    purchase.status = "CANCELLED"
    session.flush()
    return purchase


class PurchaseReceiptIdempotencyConflict(ValueError):
    """Raised when a receipt retry key is reused for different receiving details."""


def purchase_receipt_reference_type(idempotency_key: UUID) -> str:
    """Encode a UUID in the existing 30-character reference_type column."""
    encoded = base64.b32encode(idempotency_key.bytes).decode("ascii").rstrip("=")
    return f"PR-{encoded}"


def receive_purchase_line(
    session: Session,
    *,
    purchase_id: UUID,
    purchase_line_id: UUID,
    location_id: UUID,
    received_quantity: Decimal,
    idempotency_key: UUID | None = None,
) -> InventoryMovement:
    if not isinstance(received_quantity, Decimal) or received_quantity <= 0:
        raise ValueError("本次驗收數量必須是正數 Decimal。")

    # Keyed requests lock the company before locking purchase rows. This
    # serializes the first receipt and a replay, even across different POs.
    purchase_company_id = session.scalar(
        select(Purchase.company_id).where(Purchase.id == purchase_id)
    )
    if purchase_company_id is None:
        raise ValueError("找不到指定採購單。")
    if idempotency_key is not None:
        company = session.scalar(
            select(Company).where(Company.id == purchase_company_id).with_for_update()
        )
        if company is None:
            raise ValueError("找不到指定公司。")

    purchase = session.execute(
        select(Purchase).where(Purchase.id == purchase_id).with_for_update()
    ).scalar_one_or_none()
    if purchase is None:
        raise ValueError("找不到指定採購單。")
    line = session.execute(select(PurchaseLine).where(
        PurchaseLine.id == purchase_line_id, PurchaseLine.purchase_id == purchase_id
    ).with_for_update()).scalar_one_or_none()
    if line is None:
        raise ValueError("採購明細不存在。")

    reference_type = (
        purchase_receipt_reference_type(idempotency_key)
        if idempotency_key is not None else "PURCHASE_LINE"
    )
    note = f"採購單 {purchase.purchase_no} 驗收入庫"

    # Check for a committed receipt before validating the remaining quantity
    # or purchase status; an exact replay may arrive after the line is fully received.
    if idempotency_key is not None:
        existing = session.scalar(select(InventoryMovement).where(
            InventoryMovement.company_id == purchase.company_id,
            InventoryMovement.reference_type == reference_type,
        ))
        if existing is not None:
            matches = (
                existing.reference_id == line.id
                and existing.movement_type == "RECEIPT"
                and existing.site_id == purchase.site_id
                and existing.product_id == line.product_id
                and existing.from_location_id is None
                and existing.to_location_id == location_id
                and existing.quantity == received_quantity
                and existing.weight_unit_code == line.weight_unit_code
                and existing.note == note
            )
            if not matches:
                raise PurchaseReceiptIdempotencyConflict(
                    "此驗收識別碼已用於不同的採購到貨內容，請確認原入庫紀錄後再操作。"
                )
            return existing

    if purchase.status not in {"ORDERED", "PARTIALLY_RECEIVED"}:
        raise ValueError("只有已下單或部分到貨的採購單可以驗收。")
    if line.received_quantity + received_quantity > line.quantity:
        raise ValueError("本次驗收數量超過尚未到貨數量。")

    supplier = session.get(Supplier, purchase.supplier_id)
    site = session.get(Site, purchase.site_id)
    company = session.get(Company, purchase.company_id)
    product = session.execute(
        select(Product).where(Product.id == line.product_id).with_for_update()
    ).scalar_one_or_none()
    location = session.get(StorageLocation, location_id)
    if company is None or supplier is None or supplier.company_id != purchase.company_id:
        raise ValueError("供應商不存在或不屬於採購單公司。")
    if site is None or site.company_id != purchase.company_id:
        raise ValueError("採購據點不存在或不屬於採購單公司。")
    if product is None or product.company_id != purchase.company_id:
        raise ValueError("商品不存在或不屬於採購單公司。")
    if location is None or location.site_id != purchase.site_id or not location.is_active:
        raise ValueError("入庫儲存位置不存在、未啟用或不屬於採購據點。")

    receipt_weight = None
    if line.weight is not None:
        previous_weights = session.scalars(select(InventoryMovement.weight).where(
            or_(
                InventoryMovement.reference_type == "PURCHASE_LINE",
                InventoryMovement.reference_type.like("PR-%"),
            ),
            InventoryMovement.reference_id == line.id,
            InventoryMovement.movement_type == "RECEIPT",
        )).all()
        previously_received_weight = sum(
            (value or Decimal("0") for value in previous_weights), Decimal("0")
        )
        if line.received_quantity + received_quantity == line.quantity:
            receipt_weight = line.weight - previously_received_weight
        else:
            receipt_weight = (
                line.weight * received_quantity / line.quantity
            ).quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP)

    movement = InventoryMovement(
        company_id=purchase.company_id, site_id=purchase.site_id, product_id=line.product_id,
        movement_type="RECEIPT", to_location_id=location_id, quantity=received_quantity,
        weight=receipt_weight, weight_unit_code=line.weight_unit_code,
        reference_type=reference_type, reference_id=line.id,
        note=note,
    )
    line.received_quantity += received_quantity
    session.add(movement)
    session.flush()
    lines = session.scalars(select(PurchaseLine).where(PurchaseLine.purchase_id == purchase_id)).all()
    if all(item.received_quantity == item.quantity for item in lines):
        purchase.status = "RECEIVED"
    elif any(item.received_quantity > 0 for item in lines):
        purchase.status = "PARTIALLY_RECEIVED"
    return movement
