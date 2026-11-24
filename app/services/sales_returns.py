"""Item-level sales return and inventory restocking services."""
from datetime import datetime, timezone
from decimal import Decimal
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.sale import Sale, SaleLine
from app.models.sale_return import SaleReturn, SaleReturnLine
from app.services.inventory import create_inventory_movement
from app.services.daily_closing import assert_business_day_open


class SaleReturnIdempotencyConflict(ValueError):
    """Raised when a return number is reused for different return details."""


def create_sale_return(
    session: Session,
    *,
    company_id: UUID,
    sale_id: UUID,
    return_no: str,
    sale_line_ids: list[UUID],
    reason: str | None = None,
    note: str | None = None,
    return_created: bool = False,
) -> SaleReturn | tuple[SaleReturn, bool]:
    """Return individually tracked items from a completed sale.

    The signed reversal uses the opposite sign of the original line settlement:
    negative means the store owes the customer; positive means the customer owes
    the store. This records the settlement obligation only; it does not move cash.
    """
    if not sale_line_ids:
        raise ValueError("退貨明細不可空白。")
    if len(sale_line_ids) != len(set(sale_line_ids)):
        raise ValueError("退貨明細不可重複指定同一商品。")

    sale = session.execute(
        select(Sale)
        .where(Sale.id == sale_id, Sale.company_id == company_id)
        .with_for_update()
    ).scalar_one_or_none()
    if sale is None:
        raise ValueError("找不到指定銷售單。")
    if sale.status != "COMPLETED":
        raise ValueError("只有已完成的銷售單可以退貨。")

    normalized_return_no = return_no.strip()
    if not normalized_return_no:
        raise ValueError("退貨單號不可空白。")

    # A repeated request must return the committed return before checking the
    # business-day lock. This covers a lost HTTP response followed by a retry
    # after the business day has already been closed.
    existing = session.execute(
        select(SaleReturn).where(
            SaleReturn.site_id == sale.site_id,
            SaleReturn.return_no == normalized_return_no,
        ).with_for_update()
    ).scalar_one_or_none()
    if existing is not None:
        existing_line_ids = set(session.scalars(
            select(SaleReturnLine.sale_line_id).where(
                SaleReturnLine.return_id == existing.id
            )
        ).all())
        same_request = (
            existing.company_id == company_id
            and existing.sale_id == sale.id
            and existing.return_no == normalized_return_no
            and existing_line_ids == set(sale_line_ids)
            and existing.reason == reason
            and existing.note == note
        )
        if not same_request:
            raise SaleReturnIdempotencyConflict(
                "此退貨單號已用於不同退貨內容；請查閱原退貨紀錄，不可使用相同單號重複退貨。"
            )
        return (existing, False) if return_created else existing

    returned_at = datetime.now(timezone.utc)
    assert_business_day_open(session, site_id=sale.site_id, at=returned_at)

    lines = list(session.scalars(
        select(SaleLine)
        .where(SaleLine.sale_id == sale.id, SaleLine.id.in_(sale_line_ids))
        .order_by(SaleLine.line_no)
        .with_for_update()
    ).all())
    if len(lines) != len(sale_line_ids):
        raise ValueError("部分退貨明細不屬於指定銷售單。")

    already_returned = set(session.scalars(
        select(SaleReturnLine.sale_line_id)
        .where(SaleReturnLine.sale_line_id.in_(sale_line_ids))
    ).all())
    if already_returned:
        raise ValueError("所選商品已有退貨紀錄，不可重複退貨。")

    for line in lines:
        if (line.product_id is None) != (line.source_location_id is None):
            raise ValueError("原銷售明細的商品與出貨位置資料不完整。")

    return_record = SaleReturn(
        company_id=company_id,
        site_id=sale.site_id,
        sale_id=sale.id,
        return_no=normalized_return_no,
        settlement_reversal_amount=Decimal("0"),
        currency_code=sale.currency_code,
        created_at=returned_at,
        reason=reason,
        note=note,
    )
    session.add(return_record)
    session.flush()

    total_reversal = Decimal("0")
    for sale_line in lines:
        reversal = -sale_line.final_amount
        return_line = SaleReturnLine(
            return_id=return_record.id,
            sale_line_id=sale_line.id,
            product_id=sale_line.product_id,
            source_location_id=sale_line.source_location_id,
            product_code_snapshot=sale_line.product_code_snapshot,
            barcode_snapshot=sale_line.barcode_snapshot,
            product_name_snapshot=sale_line.product_name_snapshot,
            net_weight=sale_line.net_weight,
            weight_unit_code=sale_line.weight_unit_code,
            settlement_reversal_amount=reversal,
        )
        session.add(return_line)
        session.flush()

        if sale_line.product_id is not None and sale_line.source_location_id is not None:
            create_inventory_movement(
                session,
                company_id=company_id,
                site_id=sale.site_id,
                product_id=sale_line.product_id,
                movement_type="RETURN",
                quantity=Decimal("1"),
                to_location_id=sale_line.source_location_id,
                weight=sale_line.net_weight,
                weight_unit_code=sale_line.weight_unit_code,
                reference_type="SALE_RETURN_LINE",
                reference_id=return_line.id,
                note=f"退貨單 {normalized_return_no}；原銷售單 {sale.sale_no}",
            )
        total_reversal += reversal

    return_record.settlement_reversal_amount = total_reversal
    session.flush()
    return (return_record, True) if return_created else return_record
