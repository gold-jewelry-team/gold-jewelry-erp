from datetime import date, datetime, time, timedelta
from uuid import UUID
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, selectinload

from app.db.session import SessionLocal
from app.models.sale import Sale, SaleLine
from app.routers.schemas.sales import SaleActionResult, SaleCreate, SaleRead
from app.services.sales import complete_sale, create_sale_draft, update_sale_draft, void_sale_draft

router = APIRouter(prefix="/companies/{company_id}/sales", tags=["sales"])


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def _load_sale(db: Session, company_id: UUID, sale_id: UUID) -> Sale | None:
    return db.scalar(
        select(Sale)
        .options(selectinload(Sale.lines))
        .where(Sale.company_id == company_id, Sale.id == sale_id)
    )


@router.get("", response_model=list[SaleRead])
def list_sales(
    company_id: UUID,
    site_id: UUID | None = None,
    q: str | None = None,
    status: str | None = Query(default=None, pattern="^(DRAFT|COMPLETED|VOID)$"),
    from_date: date | None = None,
    to_date: date | None = None,
    limit: int = Query(default=100, ge=1, le=500),
    db: Session = Depends(get_db),
):
    statement = (
        select(Sale)
        .options(selectinload(Sale.lines))
        .where(Sale.company_id == company_id)
    )
    if site_id is not None:
        statement = statement.where(Sale.site_id == site_id)
    if status is not None:
        statement = statement.where(Sale.status == status)
    if q and q.strip():
        pattern = f"%{q.strip()}%"
        statement = statement.where(or_(
            Sale.sale_no.ilike(pattern),
            Sale.lines.any(or_(
                SaleLine.product_code_snapshot.ilike(pattern),
                SaleLine.barcode_snapshot.ilike(pattern),
                SaleLine.product_name_snapshot.ilike(pattern),
            )),
        ))
    taipei = ZoneInfo("Asia/Taipei")
    if from_date is not None:
        statement = statement.where(
            Sale.created_at >= datetime.combine(from_date, time.min, tzinfo=taipei)
        )
    if to_date is not None:
        statement = statement.where(
            Sale.created_at < datetime.combine(to_date + timedelta(days=1), time.min, tzinfo=taipei)
        )
    if from_date is not None and to_date is not None and to_date < from_date:
        raise HTTPException(status_code=422, detail="結束日期不可早於起始日期。")
    return list(db.scalars(
        statement.order_by(Sale.created_at.desc(), Sale.sale_no.desc()).limit(limit)
    ).all())


@router.post("", response_model=SaleRead, status_code=201)
def create_sale(company_id: UUID, payload: SaleCreate, db: Session = Depends(get_db)):
    try:
        sale = create_sale_draft(
            db,
            company_id=company_id,
            site_id=payload.site_id,
            sale_no=payload.sale_no,
            payment_method=payload.payment_method,
            card_amount=payload.card_amount,
            lines=[line.model_dump() for line in payload.lines],
            note=payload.note,
        )
        sale_id = sale.id
        db.commit()
        result = _load_sale(db, company_id, sale_id)
        return result
    except ValueError as exc:
        db.rollback()
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail="銷售單號重複或資料關聯衝突。") from exc


@router.get("/{sale_id}", response_model=SaleRead)
def get_sale(company_id: UUID, sale_id: UUID, db: Session = Depends(get_db)):
    sale = _load_sale(db, company_id, sale_id)
    if sale is None:
        raise HTTPException(status_code=404, detail="找不到指定銷售單。")
    return sale


@router.patch("/{sale_id}", response_model=SaleRead)
def patch_sale(company_id: UUID, sale_id: UUID, payload: SaleCreate, db: Session = Depends(get_db)):
    sale = db.scalar(select(Sale).where(Sale.id == sale_id, Sale.company_id == company_id))
    if sale is None:
        raise HTTPException(status_code=404, detail="找不到指定銷售單。")
    if payload.site_id != sale.site_id:
        raise HTTPException(status_code=422, detail="銷售草稿不可變更所屬據點。")
    try:
        update_sale_draft(
            db, company_id=company_id, sale_id=sale_id, sale_no=payload.sale_no,
            payment_method=payload.payment_method, card_amount=payload.card_amount,
            lines=[line.model_dump() for line in payload.lines], note=payload.note,
        )
        db.commit()
        return _load_sale(db, company_id, sale_id)
    except ValueError as exc:
        db.rollback()
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail="銷售單號重複或資料關聯衝突。") from exc


@router.post("/{sale_id}/complete", response_model=SaleRead)
def post_complete_sale(company_id: UUID, sale_id: UUID, db: Session = Depends(get_db)):
    try:
        complete_sale(db, company_id=company_id, sale_id=sale_id)
        db.commit()
        return _load_sale(db, company_id, sale_id)
    except ValueError as exc:
        db.rollback()
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post("/{sale_id}/void", response_model=SaleActionResult)
def post_void_sale(company_id: UUID, sale_id: UUID, db: Session = Depends(get_db)):
    try:
        sale = void_sale_draft(db, company_id=company_id, sale_id=sale_id)
        db.commit()
        return SaleActionResult(sale_id=sale.id, status=sale.status, message="銷售草稿已作廢。")
    except ValueError as exc:
        db.rollback()
        raise HTTPException(status_code=422, detail=str(exc)) from exc
