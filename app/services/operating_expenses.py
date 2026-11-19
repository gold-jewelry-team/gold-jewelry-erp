"""Operating expense workflows."""
from datetime import datetime, timezone
from decimal import Decimal
from uuid import UUID
from sqlalchemy import select
from sqlalchemy.orm import Session
from app.models.operating_expense import OperatingExpense
from app.models.site import Site
from app.services.daily_closing import assert_business_day_open

CATEGORIES = {"RENT","UTILITIES","SALARIES","SUPPLIES","SHIPPING","REPAIR","OTHER"}
METHODS = {"CASH","CARD","TRANSFER","OTHER"}

def create_expense(session: Session, *, company_id: UUID, site_id: UUID, expense_no: str,
                   expense_date, category_code: str, description: str, amount: Decimal,
                   payee: str | None = None, payment_method: str | None = None,
                   receipt_no: str | None = None, note: str | None = None) -> OperatingExpense:
    if category_code not in CATEGORIES:
        raise ValueError("不支援的營業費用分類。")
    if not isinstance(amount, Decimal) or amount <= 0 or amount.quantize(Decimal("0.01")) != amount:
        raise ValueError("費用金額必須是大於零且最多兩位小數的 Decimal。")
    if payment_method is not None and payment_method not in METHODS:
        raise ValueError("不支援的付款方式。")
    site = session.get(Site, site_id)
    if site is None or site.company_id != company_id:
        raise ValueError("據點不存在或不屬於指定公司。")
    paid_at = None
    status = "UNPAID"
    if payment_method:
        paid_at = datetime.now(timezone.utc)
        assert_business_day_open(session, site_id=site_id, at=paid_at)
        status = "PAID"
    row = OperatingExpense(company_id=company_id, site_id=site_id, expense_no=expense_no,
        expense_date=expense_date, category_code=category_code, description=description,
        payee=payee, amount=amount, currency_code="TWD", status=status,
        payment_method=payment_method, paid_at=paid_at, receipt_no=receipt_no, note=note)
    session.add(row)
    session.flush()
    return row

def pay_expense(session: Session, *, company_id: UUID, expense_id: UUID, payment_method: str) -> OperatingExpense:
    if payment_method not in METHODS:
        raise ValueError("不支援的付款方式。")
    row = session.execute(select(OperatingExpense).where(
        OperatingExpense.company_id == company_id, OperatingExpense.id == expense_id
    ).with_for_update()).scalar_one_or_none()
    if row is None:
        raise ValueError("找不到指定營業費用。")
    if row.status != "UNPAID":
        raise ValueError("只有未付款費用可以付款或作廢。")
    paid_at = datetime.now(timezone.utc)
    assert_business_day_open(session, site_id=row.site_id, at=paid_at)
    row.status = "PAID"
    row.payment_method = payment_method
    row.paid_at = paid_at
    session.flush()
    return row
