from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, selectinload

from app.db.session import SessionLocal
from app.models.sale import Sale
from app.routers.schemas.sales import SaleActionResult, SaleCreate, SaleRead
from app.services.sales import complete_sale, create_sale_draft, void_sale_draft

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


@router.post("", response_model=SaleRead, status_code=201)
def create_sale(company_id: UUID, payload: SaleCreate, db: Session = Depends(get_db)):
    try:
        sale = create_sale_draft(
            db,
            company_id=company_id,
            site_id=payload.site_id,
            sale_no=payload.sale_no,
            payment_method=payload.payment_method,
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
