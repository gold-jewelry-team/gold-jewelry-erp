from datetime import date, datetime, time, timedelta
from uuid import UUID
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, selectinload

from app.db.session import SessionLocal
from app.models.company import Company
from app.models.customer_order import CustomerOrder
from app.models.payment_transaction import PaymentTransaction
from app.models.site import Site
from app.routers.schemas.customer_orders import CustomerOrderCreate, CustomerOrderPaymentCreate, CustomerOrderRead, CustomerOrderUpdate
from app.services.payments import (
    CustomerOrderPaymentIdempotencyConflict,
    record_customer_order_payment,
)


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


def _normalize_order_datetime(value: datetime | None) -> datetime | None:
    """Keep naive delivery times interpreted as Taipei local time."""
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=ZoneInfo("Asia/Taipei"))
    return value


def _same_order_datetime(left: datetime | None, right: datetime | None) -> bool:
    if left is None or right is None:
        return left is None and right is None

    def as_utc(value: datetime) -> datetime:
        if value.tzinfo is None:
            value = value.replace(tzinfo=ZoneInfo("Asia/Taipei"))
        return value.astimezone(ZoneInfo("UTC"))

    return as_utc(left) == as_utc(right)


def _customer_order_create_matches(
    order: CustomerOrder,
    initial_payment: PaymentTransaction,
    payload: CustomerOrderCreate,
    *,
    idempotency_reference: str,
) -> bool:
    return (
        initial_payment.reference_no == idempotency_reference
        and initial_payment.customer_order_id == order.id
        and initial_payment.company_id == order.company_id
        and initial_payment.site_id == order.site_id
        and initial_payment.direction == "IN"
        and initial_payment.payment_method == payload.payment_method
        and initial_payment.amount == payload.initial_deposit
        and initial_payment.currency_code == order.currency_code
        and initial_payment.note == "建立訂購單時收取訂金"
        and order.site_id == payload.site_id
        and order.order_no == payload.order_no
        and order.customer_name == payload.customer_name.strip()
        and order.customer_phone == payload.customer_phone
        and _same_order_datetime(order.expected_delivery_date, payload.expected_delivery_date)
        and order.items == payload.items
        and order.total_amount == payload.total_amount
        and order.deposit_amount >= payload.initial_deposit
        and order.note == payload.note
    )


@router.post("", response_model=CustomerOrderRead, status_code=201)
def create_customer_order(
    company_id: UUID,
    payload: CustomerOrderCreate,
    response: Response,
    db: Session = Depends(get_db),
):
    site = db.scalar(select(Site).where(Site.id == payload.site_id, Site.company_id == company_id))
    if site is None:
        raise HTTPException(status_code=422, detail="指定據點不屬於目前公司。")

    idempotency_reference = (
        f"CO-CREATE:{payload.idempotency_key}"
        if payload.idempotency_key is not None else None
    )
    try:
        if idempotency_reference is not None:
            company = db.scalar(
                select(Company).where(Company.id == company_id).with_for_update()
            )
            if company is None:
                raise ValueError("找不到指定公司。")
            existing_payment = db.scalar(select(PaymentTransaction).where(
                PaymentTransaction.company_id == company_id,
                PaymentTransaction.reference_no == idempotency_reference,
            ))
            if existing_payment is not None:
                existing_order = db.scalar(select(CustomerOrder).where(
                    CustomerOrder.id == existing_payment.customer_order_id,
                    CustomerOrder.company_id == company_id,
                ).with_for_update())
                if existing_order is None or existing_order.company_id != company_id:
                    db.rollback()
                    raise HTTPException(
                        status_code=409,
                        detail="此建立識別碼已有付款紀錄，但找不到對應訂單，請先核對帳務。",
                    )
                if not _customer_order_create_matches(
                    existing_order,
                    existing_payment,
                    payload,
                    idempotency_reference=idempotency_reference,
                ):
                    db.rollback()
                    raise HTTPException(
                        status_code=409,
                        detail="此建立識別碼已用於不同的客訂內容，請確認原訂單後再操作。",
                    )
                response.status_code = 200
                order_id = existing_order.id
                db.commit()
                return _load(db, company_id, order_id)

        order = CustomerOrder(
            company_id=company_id,
            site_id=payload.site_id,
            order_no=payload.order_no,
            customer_name=payload.customer_name.strip(),
            customer_phone=payload.customer_phone,
            expected_delivery_date=_normalize_order_datetime(payload.expected_delivery_date),
            items=payload.items,
            total_amount=payload.total_amount,
            deposit_amount=0,
            status="PENDING_DEPOSIT",
            note=payload.note,
        )
        db.add(order)
        db.flush()
        record_customer_order_payment(
            db,
            company_id=company_id,
            order_id=order.id,
            payment_method=payload.payment_method,
            amount=payload.initial_deposit,
            note="建立訂購單時收取訂金",
            idempotency_key=payload.idempotency_key,
            idempotency_prefix="CO-CREATE",
        )
        order.status = "IN_PROGRESS"
        order_id = order.id
        db.commit()
        return _load(db, company_id, order_id)
    except HTTPException:
        raise
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


@router.patch("/{order_id}", response_model=CustomerOrderRead)
def update_customer_order(
    company_id: UUID, order_id: UUID, payload: CustomerOrderUpdate,
    db: Session = Depends(get_db),
):
    order = db.scalar(select(CustomerOrder).where(
        CustomerOrder.company_id == company_id,
        CustomerOrder.id == order_id,
    ).with_for_update())
    if order is None:
        raise HTTPException(status_code=404, detail="找不到指定客訂單。")
    if order.status != "IN_PROGRESS":
        raise HTTPException(status_code=409, detail="只有進行中的客訂單可以修改基本資料；已到貨或已完成訂單不可直接更改。")
    changes = payload.model_dump(exclude_unset=True)
    if not changes:
        raise HTTPException(status_code=422, detail="請至少提供一個要修改的欄位。")
    if any(changes.get(field) is None for field in ("order_no", "customer_name") if field in changes):
        raise HTTPException(status_code=422, detail="訂單編號與客戶姓名不可為空。")
    if "order_no" in changes and changes["order_no"] is not None:
        order.order_no = changes["order_no"]
    if "customer_name" in changes and changes["customer_name"] is not None:
        order.customer_name = changes["customer_name"].strip()
    if "customer_phone" in changes:
        order.customer_phone = changes["customer_phone"]
    if "expected_delivery_date" in changes:
        order.expected_delivery_date = _normalize_order_datetime(changes["expected_delivery_date"])
    if "note" in changes:
        order.note = changes["note"]
    try:
        db.commit()
        return _load(db, company_id, order_id)
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail="客訂單編號重複或資料關聯衝突。") from exc


@router.post("/{order_id}/payments", response_model=CustomerOrderRead)
def add_customer_order_payment(company_id: UUID, order_id: UUID, payload: CustomerOrderPaymentCreate, db: Session = Depends(get_db)):
    order = _load(db, company_id, order_id)
    if order is None:
        raise HTTPException(status_code=404, detail="找不到指定客訂單。")
    try:
        record_customer_order_payment(
            db, company_id=company_id, order_id=order.id,
            payment_method=payload.payment_method, amount=payload.amount, note=payload.note,
            idempotency_key=payload.idempotency_key,
        )
        db.commit()
        return _load(db, company_id, order.id)
    except CustomerOrderPaymentIdempotencyConflict as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail=str(exc)) from exc
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
