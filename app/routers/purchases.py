from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, selectinload

from app.db.session import SessionLocal
from app.models.company import Company
from app.models.purchase import Purchase
from app.routers.schemas.purchasing import PurchaseActionResult, PurchaseCreate, PurchaseRead, PurchaseReceive
from app.services.purchasing import cancel_purchase, create_purchase, receive_purchase_line, submit_purchase

router = APIRouter(prefix="/companies/{company_id}/purchases", tags=["purchases"])


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def _get_purchase(db: Session, company_id: UUID, purchase_id: UUID):
    return db.scalar(select(Purchase).where(
        Purchase.id == purchase_id, Purchase.company_id == company_id
    ).options(selectinload(Purchase.lines)))


@router.get("", response_model=list[PurchaseRead])
def list_purchases(company_id: UUID,
                   status: str | None = Query(default=None, pattern="^(DRAFT|ORDERED|PARTIALLY_RECEIVED|RECEIVED|CANCELLED)$"),
                   limit: int = Query(default=100, ge=1, le=500),
                   db: Session = Depends(get_db)):
    if db.get(Company, company_id) is None:
        raise HTTPException(status_code=404, detail="找不到指定公司。")
    statement = select(Purchase).where(Purchase.company_id == company_id).options(selectinload(Purchase.lines))
    if status:
        statement = statement.where(Purchase.status == status)
    return list(db.scalars(statement.order_by(Purchase.order_date.desc()).limit(limit)).all())


@router.post("", response_model=PurchaseRead, status_code=201)
def post_purchase(company_id: UUID, payload: PurchaseCreate, db: Session = Depends(get_db)):
    try:
        purchase = create_purchase(
            db, company_id=company_id, site_id=payload.site_id, supplier_id=payload.supplier_id,
            purchase_no=payload.purchase_no, order_date=payload.order_date,
            expected_date=payload.expected_date, currency_code=payload.currency_code,
            note=payload.note, lines=[line.model_dump() for line in payload.lines],
        )
        purchase_id = purchase.id
        db.commit()
        return _get_purchase(db, company_id, purchase_id)
    except ValueError as exc:
        db.rollback()
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail="採購單號或資料關聯重複／不合法。") from exc


@router.get("/{purchase_id}", response_model=PurchaseRead)
def get_purchase(company_id: UUID, purchase_id: UUID, db: Session = Depends(get_db)):
    purchase = _get_purchase(db, company_id, purchase_id)
    if purchase is None:
        raise HTTPException(status_code=404, detail="找不到指定採購單。")
    return purchase


@router.post("/{purchase_id}/submit", response_model=PurchaseActionResult)
def post_submit_purchase(company_id: UUID, purchase_id: UUID, db: Session = Depends(get_db)):
    if db.get(Company, company_id) is None:
        raise HTTPException(status_code=404, detail="找不到指定公司。")
    try:
        purchase = submit_purchase(db, purchase_id=purchase_id)
        if purchase.company_id != company_id:
            raise ValueError("找不到指定採購單。")
        db.commit()
        return PurchaseActionResult(purchase_id=purchase.id, status=purchase.status, message="採購單已送出。")
    except ValueError as exc:
        db.rollback()
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post("/{purchase_id}/cancel", response_model=PurchaseActionResult)
def post_cancel_purchase(company_id: UUID, purchase_id: UUID, db: Session = Depends(get_db)):
    if db.get(Company, company_id) is None:
        raise HTTPException(status_code=404, detail="找不到指定公司。")
    try:
        purchase = cancel_purchase(db, purchase_id=purchase_id)
        if purchase.company_id != company_id:
            raise ValueError("找不到指定採購單。")
        db.commit()
        return PurchaseActionResult(purchase_id=purchase.id, status=purchase.status, message="採購單已取消。")
    except ValueError as exc:
        db.rollback()
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post("/{purchase_id}/receive", response_model=PurchaseActionResult)
def post_receive_purchase(company_id: UUID, purchase_id: UUID, payload: PurchaseReceive,
                          db: Session = Depends(get_db)):
    if db.get(Company, company_id) is None:
        raise HTTPException(status_code=404, detail="找不到指定公司。")
    purchase = db.get(Purchase, purchase_id)
    if purchase is None or purchase.company_id != company_id:
        raise HTTPException(status_code=404, detail="找不到指定採購單。")
    try:
        receive_purchase_line(db, purchase_id=purchase_id,
                              purchase_line_id=payload.purchase_line_id,
                              location_id=payload.location_id,
                              received_quantity=payload.received_quantity)
        db.commit()
        db.refresh(purchase)
        return PurchaseActionResult(purchase_id=purchase.id, status=purchase.status,
                                    message="驗收完成，已新增庫存入庫流水。")
    except ValueError as exc:
        db.rollback()
        raise HTTPException(status_code=422, detail=str(exc)) from exc
