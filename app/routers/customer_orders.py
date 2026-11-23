from datetime import date, datetime, time, timedelta
from uuid import UUID
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, selectinload

from app.db.session import SessionLocal
from app.models.customer_order import CustomerOrder
from app.models.site import Site
from app.routers.schemas.customer_orders import CustomerOrderCreate, CustomerOrderPaymentCreate, CustomerOrderRead
from app.services.payments import record_customer_order_payment


router = APIRouter(prefix="/companies/{company_id}/customer-orders", tags=["customer-orders"])


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def _load(db: Session, company_id: UUID, order_id: UUID):
    return db.scalar(select(CustomerOrder).options(selectinload(CustomerOrder.payments)).where(
        CustomerOrder.company_id == company_id, CustomerOrder.id == order_id
    ))


@router.get("", response_model=list[CustomerOrderRead])
def list_customer_orders(
    company_id: UUID,
    site_id: UUID | None = None,
    status: str | None = Query(default=None, pattern="^(PENDING_DEPOSIT|IN_PROGRESS|ARRIVED|READY|COMPLETED|CANCELLED)$"),
    q: str | None = None,
    limit: int = Query(default=100, ge=1, le=500),
    db: Session = Depends(get_db),
):
    statement = select(CustomerOrder).options(selectinload(CustomerOrder.payments)).where(CustomerOrder.company_id == company_id)
    if site_id:
        statement = statement.where(CustomerOrder.site_id == site_id)
    if status:
        statement = statement.where(CustomerOrder.status == status)
    if q and q.strip():
        pattern = f"%{q.strip()}%"
        statement = statement.where(
            CustomerOrder.order_no.ilike(pattern)
            | CustomerOrder.customer_name.ilike(pattern)
            | CustomerOrder.customer_phone.ilike(pattern)
        )
    return list(db.scalars(statement.order_by(CustomerOrder.created_at.desc()).limit(limit)).all())


@router.post("", response_model=CustomerOrderRead, status_code=201)
def create_customer_order(company_id: UUID, payload: CustomerOrderCreate, db: Session = Depends(get_db)):
    site = db.scalar(select(Site).where(Site.id == payload.site_id, Site.company_id == company_id))
    if site is None:
        raise HTTPException(status_code=422, detail="指定據點不屬於目前公司。")
    order = CustomerOrder(
        company_id=company_id,
        site_id=payload.site_id,
        order_no=payload.order_no,
        customer_name=payload.customer_name.strip(),
        customer_phone=payload.customer_phone,
        expected_delivery_date=payload.expected_delivery_date,
        items=payload.items,
        total_amount=payload.total_amount,
        deposit_amount=0,
        status="PENDING_DEPOSIT",
        note=payload.note,
    )
    db.add(order)
    db.flush()
    try:
        record_customer_order_payment(
            db, company_id=company_id, order_id=order.id,
            payment_method=payload.payment_method, amount=payload.initial_deposit,
            note="建立訂購單時收取訂金",
        )
        order.status = "IN_PROGRESS"
        db.commit()
        return _load(db, company_id, order.id)
    except ValueError as exc:
        db.rollback()
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail="訂購單號重複或資料關聯衝突。") from exc


@router.get("/{order_id}", response_model=CustomerOrderRead)
def get_customer_order(company_id: UUID, order_id: UUID, db: Session = Depends(get_db)):
    order = _load(db, company_id, order_id)
    if order is None:
        raise HTTPException(status_code=404, detail="找不到指定客訂單。")
    return order


@router.post("/{order_id}/payments", response_model=CustomerOrderRead)
def add_customer_order_payment(company_id: UUID, order_id: UUID, payload: CustomerOrderPaymentCreate, db: Session = Depends(get_db)):
    order = _load(db, company_id, order_id)
    if order is None:
        raise HTTPException(status_code=404, detail="找不到指定客訂單。")
    try:
        record_customer_order_payment(
            db, company_id=company_id, order_id=order.id,
            payment_method=payload.payment_method, amount=payload.amount, note=payload.note,
        )
        db.commit()
        return _load(db, company_id, order.id)
    except ValueError as exc:
        db.rollback()
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.patch("/{order_id}/status", response_model=CustomerOrderRead)
def update_customer_order_status(
    company_id: UUID, order_id: UUID,
    status: str = Query(pattern="^(IN_PROGRESS|ARRIVED|READY|COMPLETED)$"),
    db: Session = Depends(get_db),
):
    order = _load(db, company_id, order_id)
    if order is None:
        raise HTTPException(status_code=404, detail="找不到指定客訂單。")
    allowed = {
        "PENDING_DEPOSIT": {"IN_PROGRESS"},
        "IN_PROGRESS": {"ARRIVED"},
        "ARRIVED": {"READY"},
        "READY": {"COMPLETED"},
    }
    if status not in allowed.get(order.status, set()):
        raise HTTPException(status_code=409, detail=f"不可由 {order.status} 變更為 {status}。")
    if status == "COMPLETED" and order.deposit_amount < order.total_amount:
        raise HTTPException(status_code=422, detail="尚有尾款未收清，不可完成交貨。")
    order.status = status
    db.commit()
    return _load(db, company_id, order.id)
