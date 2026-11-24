from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Response
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db.session import SessionLocal
from app.models.payment_transaction import PaymentTransaction
from app.routers.schemas.payments import PaymentCreate, PaymentRead
from app.services.payments import PaymentIdempotencyConflict, record_return_payment, record_sale_payment

router = APIRouter(prefix="/companies/{company_id}", tags=["payments"])


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


@router.post("/sales/{sale_id}/payments", response_model=PaymentRead, status_code=201)
def post_sale_payment(
    company_id: UUID,
    sale_id: UUID,
    payload: PaymentCreate,
    response: Response,
    db: Session = Depends(get_db),
):
    try:
        transaction, created = record_sale_payment(
            db,
            company_id=company_id,
            sale_id=sale_id,
            payment_method=payload.payment_method,
            amount=payload.amount,
            reference_no=payload.reference_no,
            note=payload.note,
            idempotency_key=payload.idempotency_key,
            return_created=True,
        )
        if not created:
            response.status_code = 200
        transaction_id = transaction.id
        db.commit()
        return db.get(PaymentTransaction, transaction_id)
    except PaymentIdempotencyConflict as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ValueError as exc:
        db.rollback()
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail="收付款紀錄與來源資料關聯衝突。") from exc


@router.get("/sales/{sale_id}/payments", response_model=list[PaymentRead])
def list_sale_payments(
    company_id: UUID,
    sale_id: UUID,
    db: Session = Depends(get_db),
):
    return list(db.scalars(
        select(PaymentTransaction)
        .where(
            PaymentTransaction.company_id == company_id,
            PaymentTransaction.sale_id == sale_id,
        )
        .order_by(PaymentTransaction.paid_at, PaymentTransaction.created_at)
    ).all())


@router.post("/sales/returns/{return_id}/payments", response_model=PaymentRead, status_code=201)
def post_return_payment(
    company_id: UUID,
    return_id: UUID,
    payload: PaymentCreate,
    response: Response,
    db: Session = Depends(get_db),
):
    try:
        transaction, created = record_return_payment(
            db,
            company_id=company_id,
            return_id=return_id,
            payment_method=payload.payment_method,
            amount=payload.amount,
            reference_no=payload.reference_no,
            note=payload.note,
            idempotency_key=payload.idempotency_key,
            return_created=True,
        )
        if not created:
            response.status_code = 200
        transaction_id = transaction.id
        db.commit()
        return db.get(PaymentTransaction, transaction_id)
    except PaymentIdempotencyConflict as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ValueError as exc:
        db.rollback()
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail="退款紀錄與來源資料關聯衝突。") from exc


@router.get("/sales/returns/{return_id}/payments", response_model=list[PaymentRead])
def list_return_payments(
    company_id: UUID,
    return_id: UUID,
    db: Session = Depends(get_db),
):
    return list(db.scalars(
        select(PaymentTransaction)
        .where(
            PaymentTransaction.company_id == company_id,
            PaymentTransaction.sale_return_id == return_id,
        )
        .order_by(PaymentTransaction.paid_at, PaymentTransaction.created_at)
    ).all())
