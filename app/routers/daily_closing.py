from datetime import date
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, selectinload

from app.db.session import SessionLocal
from app.models.daily_closing import DailyClosing
from app.models.site import Site
from app.routers.schemas.daily_closing import DailyClosingCreate, DailyClosingRead
from app.services.daily_closing import create_daily_closing

router = APIRouter(
    prefix="/companies/{company_id}/sites/{site_id}/daily-closings",
    tags=["daily closing"],
)


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def _load_closing(
    db: Session, company_id: UUID, site_id: UUID, closing_id: UUID
) -> DailyClosing | None:
    return db.scalar(
        select(DailyClosing)
        .options(selectinload(DailyClosing.payment_summaries))
        .where(
            DailyClosing.company_id == company_id,
            DailyClosing.site_id == site_id,
            DailyClosing.id == closing_id,
        )
    )


@router.post("", response_model=DailyClosingRead, status_code=201)
def post_daily_closing(
    company_id: UUID,
    site_id: UUID,
    payload: DailyClosingCreate,
    db: Session = Depends(get_db),
):
    try:
        record = create_daily_closing(
            db,
            company_id=company_id,
            site_id=site_id,
            business_date=payload.business_date,
            note=payload.note,
        )
        closing_id = record.id
        db.commit()
        result = _load_closing(db, company_id, site_id, closing_id)
        return result
    except ValueError as exc:
        db.rollback()
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail="該營業日已被其他結帳程序建立。") from exc


@router.get("", response_model=list[DailyClosingRead])
def list_daily_closings(
    company_id: UUID,
    site_id: UUID,
    from_date: date | None = Query(default=None),
    to_date: date | None = Query(default=None),
    db: Session = Depends(get_db),
):
    site = db.get(Site, site_id)
    if site is None or site.company_id != company_id:
        raise HTTPException(status_code=404, detail="找不到指定營運據點。")
    if from_date and to_date and from_date > to_date:
        raise HTTPException(status_code=422, detail="起始日期不可晚於結束日期。")
    statement = (
        select(DailyClosing)
        .options(selectinload(DailyClosing.payment_summaries))
        .where(DailyClosing.company_id == company_id, DailyClosing.site_id == site_id)
        .order_by(DailyClosing.business_date.desc())
    )
    if from_date:
        statement = statement.where(DailyClosing.business_date >= from_date)
    if to_date:
        statement = statement.where(DailyClosing.business_date <= to_date)
    return list(db.scalars(statement).all())


@router.get("/{closing_id}", response_model=DailyClosingRead)
def get_daily_closing(
    company_id: UUID,
    site_id: UUID,
    closing_id: UUID,
    db: Session = Depends(get_db),
):
    record = _load_closing(db, company_id, site_id, closing_id)
    if record is None:
        raise HTTPException(status_code=404, detail="找不到指定每日結帳紀錄。")
    return record
