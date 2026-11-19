from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, selectinload

from app.db.session import SessionLocal
from app.models.sale_return import SaleReturn
from app.routers.schemas.sales_returns import SaleReturnCreate, SaleReturnRead
from app.services.sales_returns import create_sale_return

router = APIRouter(
    prefix="/companies/{company_id}/sales/{sale_id}/returns",
    tags=["sales returns"],
)


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def _load_return(
    db: Session, company_id: UUID, sale_id: UUID, return_id: UUID
) -> SaleReturn | None:
    return db.scalar(
        select(SaleReturn)
        .options(selectinload(SaleReturn.lines))
        .where(
            SaleReturn.company_id == company_id,
            SaleReturn.sale_id == sale_id,
            SaleReturn.id == return_id,
        )
    )


@router.get("", response_model=list[SaleReturnRead])
def list_sale_returns(
    company_id: UUID,
    sale_id: UUID,
    db: Session = Depends(get_db),
):
    return list(db.scalars(
        select(SaleReturn)
        .options(selectinload(SaleReturn.lines))
        .where(SaleReturn.company_id == company_id, SaleReturn.sale_id == sale_id)
        .order_by(SaleReturn.created_at, SaleReturn.id)
    ).all())


@router.post("", response_model=SaleReturnRead, status_code=201)
def post_sale_return(
    company_id: UUID,
    sale_id: UUID,
    payload: SaleReturnCreate,
    db: Session = Depends(get_db),
):
    try:
        record = create_sale_return(
            db,
            company_id=company_id,
            sale_id=sale_id,
            return_no=payload.return_no,
            sale_line_ids=payload.sale_line_ids,
            reason=payload.reason,
            note=payload.note,
        )
        return_id = record.id
        db.commit()
        return _load_return(db, company_id, sale_id, return_id)
    except ValueError as exc:
        db.rollback()
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(
            status_code=409,
            detail="退貨單號重複，或商品已被其他退貨單處理。",
        ) from exc


@router.get("/{return_id}", response_model=SaleReturnRead)
def get_sale_return(
    company_id: UUID,
    sale_id: UUID,
    return_id: UUID,
    db: Session = Depends(get_db),
):
    record = _load_return(db, company_id, sale_id, return_id)
    if record is None:
        raise HTTPException(status_code=404, detail="找不到指定退貨單。")
    return record
