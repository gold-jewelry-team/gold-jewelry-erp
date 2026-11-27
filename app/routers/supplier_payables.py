from datetime import date
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, selectinload

from app.db.session import SessionLocal
from app.core.company_access import require_current_actor_permission
from app.models.purchase import Purchase
from app.models.supplier_payable import (
    SupplierBill, SupplierPayment, SupplierPaymentAllocation, SupplierPaymentReversal,
)
from app.routers.schemas.supplier_payables import (
    SupplierBillCreate,
    SupplierBillRead,
    SupplierBillUpdate,
    SupplierPaymentCreate,
    SupplierPaymentRead,
    SupplierPaymentReversalCreate,
    SupplierPaymentReversalRead,
    SupplierPayableAgingRead,
)
from app.services.supplier_payables import (
    SupplierBillIdempotencyConflict,
    SupplierPaymentIdempotencyConflict,
    SupplierPaymentReversalIdempotencyConflict,
    create_supplier_bill,
    record_supplier_payment,
    record_supplier_payment_reversal,
    get_supplier_payable_aging,
)

router = APIRouter(prefix="/companies/{company_id}/supplier-payables", tags=["supplier payables"])


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def _load_bill(db: Session, company_id: UUID, bill_id: UUID) -> SupplierBill | None:
    return db.scalar(
        select(SupplierBill)
        .options(selectinload(SupplierBill.allocations))
        .where(SupplierBill.company_id == company_id, SupplierBill.id == bill_id)
    )


def _load_payment(db: Session, company_id: UUID, payment_id: UUID) -> SupplierPayment | None:
    return db.scalar(
        select(SupplierPayment)
        .options(
            selectinload(SupplierPayment.allocations).selectinload(
                SupplierPaymentAllocation.reversal_allocations
            ),
            selectinload(SupplierPayment.reversals),
        )
        .where(SupplierPayment.company_id == company_id, SupplierPayment.id == payment_id)
    )



@router.get("/aging", response_model=SupplierPayableAgingRead)
def get_supplier_payable_aging_report(
    company_id: UUID,
    site_id: UUID | None = None,
    supplier_id: UUID | None = None,
    as_of_date: date | None = None,
    db: Session = Depends(get_db),
):
    return get_supplier_payable_aging(
        db,
        company_id=company_id,
        site_id=site_id,
        supplier_id=supplier_id,
        as_of_date=as_of_date,
    )


@router.post("/bills", response_model=SupplierBillRead, status_code=201)
def post_supplier_bill(
    company_id: UUID,
    payload: SupplierBillCreate,
    response: Response,
    db: Session = Depends(get_db),
):
    if payload.purchase_id is not None:
        require_current_actor_permission(db, "purchases.view")
    try:
        bill, created = create_supplier_bill(
            db,
            company_id=company_id,
            site_id=payload.site_id,
            supplier_id=payload.supplier_id,
            purchase_id=payload.purchase_id,
            bill_no=payload.bill_no,
            bill_date=payload.bill_date,
            due_date=payload.due_date,
            currency_code=payload.currency_code,
            total_amount=payload.total_amount,
            note=payload.note,
            return_created=True,
        )
        bill_id = bill.id
        if not created:
            response.status_code = 200
        db.commit()
        return _load_bill(db, company_id, bill_id)
    except SupplierBillIdempotencyConflict as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ValueError as exc:
        db.rollback()
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail="供應商帳單號碼重複或資料關聯衝突。") from exc


@router.get("/bills", response_model=list[SupplierBillRead])
def list_supplier_bills(
    company_id: UUID,
    site_id: UUID | None = None,
    supplier_id: UUID | None = None,
    status: str | None = Query(default=None, pattern="^(OPEN|PARTIALLY_PAID|PAID|VOID)$"),
    due_before: date | None = None,
    limit: int = Query(default=100, ge=1, le=500),
    db: Session = Depends(get_db),
):
    statement = (
        select(SupplierBill)
        .options(selectinload(SupplierBill.allocations))
        .where(SupplierBill.company_id == company_id)
        .order_by(SupplierBill.due_date, SupplierBill.bill_date.desc())
        .limit(limit)
    )
    if site_id:
        statement = statement.where(SupplierBill.site_id == site_id)
    if supplier_id:
        statement = statement.where(SupplierBill.supplier_id == supplier_id)
    if status:
        statement = statement.where(SupplierBill.status == status)
    if due_before:
        statement = statement.where(SupplierBill.due_date <= due_before)
    return list(db.scalars(statement).all())


@router.get("/bills/{bill_id}", response_model=SupplierBillRead)
def get_supplier_bill(company_id: UUID, bill_id: UUID, db: Session = Depends(get_db)):
    bill = _load_bill(db, company_id, bill_id)
    if bill is None:
        raise HTTPException(status_code=404, detail="找不到指定供應商帳單。")
    return bill


@router.patch("/bills/{bill_id}", response_model=SupplierBillRead)
def patch_supplier_bill(
    company_id: UUID, bill_id: UUID, payload: SupplierBillUpdate,
    db: Session = Depends(get_db),
):
    bill = db.scalar(select(SupplierBill).where(
        SupplierBill.company_id == company_id, SupplierBill.id == bill_id
    ).with_for_update())
    if bill is None:
        raise HTTPException(status_code=404, detail="找不到指定供應商帳單。")
    if bill.status != "OPEN" or bill.paid_amount != 0:
        raise HTTPException(status_code=409, detail="只有尚未付款的帳單可以修改；已付款或部分付款帳單不可直接更改。")
    changes = payload.model_dump(exclude_unset=True)
    if not changes:
        raise HTTPException(status_code=422, detail="請至少提供一個要修改的欄位。")
    if any(changes.get(field) is None for field in ("bill_no", "bill_date", "currency_code", "total_amount") if field in changes):
        raise HTTPException(status_code=422, detail="帳單號碼、日期、幣別與總額不可為空。")
    effective_bill_date = changes.get("bill_date", bill.bill_date)
    effective_due_date = changes.get("due_date", bill.due_date)
    if effective_due_date is not None and effective_due_date < effective_bill_date:
        raise HTTPException(status_code=422, detail="到期日不可早於帳單日期。")
    if bill.purchase_id is not None and "currency_code" in changes:
        require_current_actor_permission(db, "purchases.view")
        purchase = db.get(Purchase, bill.purchase_id)
        if purchase is None or changes["currency_code"].upper() != purchase.currency_code:
            raise HTTPException(status_code=422, detail="帳單幣別必須與關聯採購單一致。")
    for key, value in changes.items():
        if key == "currency_code" and value is not None:
            value = value.upper()
        setattr(bill, key, value)
    try:
        db.commit()
        return _load_bill(db, company_id, bill_id)
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail="供應商帳單號碼重複或資料關聯衝突。") from exc


@router.post("/bills/{bill_id}/void", response_model=SupplierBillRead)
def void_supplier_bill(company_id: UUID, bill_id: UUID, db: Session = Depends(get_db)):
    bill = db.scalar(select(SupplierBill).where(
        SupplierBill.company_id == company_id, SupplierBill.id == bill_id
    ).with_for_update())
    if bill is None:
        raise HTTPException(status_code=404, detail="找不到指定供應商帳單。")
    if bill.status != "OPEN" or bill.paid_amount != 0:
        raise HTTPException(status_code=409, detail="只有尚未付款的帳單可以作廢；已付款或部分付款帳單不可直接作廢。")
    bill.status = "VOID"
    try:
        db.commit()
        return _load_bill(db, company_id, bill_id)
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail="供應商帳單作廢失敗。") from exc


@router.post("/payments", response_model=SupplierPaymentRead, status_code=201)
def post_supplier_payment(
    company_id: UUID,
    payload: SupplierPaymentCreate,
    response: Response,
    db: Session = Depends(get_db),
):
    require_current_actor_permission(db, "suppliers.view")
    try:
        payment, created = record_supplier_payment(
            db,
            company_id=company_id,
            site_id=payload.site_id,
            supplier_id=payload.supplier_id,
            payment_no=payload.payment_no,
            payment_method=payload.payment_method,
            allocations=[item.model_dump() for item in payload.allocations],
            reference_no=payload.reference_no,
            note=payload.note,
            return_created=True,
        )
        payment_id = payment.id
        if not created:
            response.status_code = 200
        db.commit()
        return _load_payment(db, company_id, payment_id)
    except SupplierPaymentIdempotencyConflict as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ValueError as exc:
        db.rollback()
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail="供應商付款單號重複或資料關聯衝突。") from exc


@router.get("/payments", response_model=list[SupplierPaymentRead])
def list_supplier_payments(
    company_id: UUID,
    site_id: UUID | None = None,
    supplier_id: UUID | None = None,
    limit: int = Query(default=100, ge=1, le=500),
    db: Session = Depends(get_db),
):
    statement = (
        select(SupplierPayment)
        .options(
            selectinload(SupplierPayment.allocations).selectinload(
                SupplierPaymentAllocation.reversal_allocations
            ),
            selectinload(SupplierPayment.reversals),
        )
        .where(SupplierPayment.company_id == company_id)
        .order_by(SupplierPayment.paid_at.desc())
        .limit(limit)
    )
    if site_id:
        statement = statement.where(SupplierPayment.site_id == site_id)
    if supplier_id:
        statement = statement.where(SupplierPayment.supplier_id == supplier_id)
    return list(db.scalars(statement).all())


@router.get("/payments/{payment_id}", response_model=SupplierPaymentRead)
def get_supplier_payment(company_id: UUID, payment_id: UUID, db: Session = Depends(get_db)):
    payment = _load_payment(db, company_id, payment_id)
    if payment is None:
        raise HTTPException(status_code=404, detail="找不到指定供應商付款紀錄。")
    return payment



def _load_reversal(
    db: Session, company_id: UUID, reversal_id: UUID
) -> SupplierPaymentReversal | None:
    return db.scalar(
        select(SupplierPaymentReversal)
        .options(selectinload(SupplierPaymentReversal.allocations))
        .where(
            SupplierPaymentReversal.company_id == company_id,
            SupplierPaymentReversal.id == reversal_id,
        )
    )


@router.post(
    "/payments/{payment_id}/reverse",
    response_model=SupplierPaymentReversalRead,
    status_code=201,
)
def post_supplier_payment_reversal(
    company_id: UUID,
    payment_id: UUID,
    payload: SupplierPaymentReversalCreate,
    response: Response,
    db: Session = Depends(get_db),
):
    require_current_actor_permission(db, "supplier_payables.void")
    require_current_actor_permission(db, "payments.void")
    try:
        reversal, created = record_supplier_payment_reversal(
            db,
            company_id=company_id,
            payment_id=payment_id,
            reversal_no=payload.reversal_no,
            allocations=[item.model_dump() for item in payload.allocations],
            reason=payload.reason,
            return_created=True,
        )
        reversal_id = reversal.id
        if not created:
            response.status_code = 200
        db.commit()
        return _load_reversal(db, company_id, reversal_id)
    except SupplierPaymentReversalIdempotencyConflict as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ValueError as exc:
        db.rollback()
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail="供應商付款沖銷單號重複或關聯衝突。") from exc


@router.get(
    "/payments/{payment_id}/reversals",
    response_model=list[SupplierPaymentReversalRead],
)
def list_supplier_payment_reversals(
    company_id: UUID,
    payment_id: UUID,
    db: Session = Depends(get_db),
):
    payment = _load_payment(db, company_id, payment_id)
    if payment is None:
        raise HTTPException(status_code=404, detail="找不到指定供應商付款紀錄。")
    return list(db.scalars(
        select(SupplierPaymentReversal)
        .options(selectinload(SupplierPaymentReversal.allocations))
        .where(
            SupplierPaymentReversal.company_id == company_id,
            SupplierPaymentReversal.payment_id == payment_id,
        )
        .order_by(SupplierPaymentReversal.reversed_at, SupplierPaymentReversal.id)
    ).all())
