"""Read-only operational period report API."""
from datetime import date
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.db.session import SessionLocal
from app.services.operational_reports import build_operational_period_report

router = APIRouter(
    prefix="/companies/{company_id}/sites/{site_id}/operational-report",
    tags=["operational reports"],
)


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


@router.get("")
def get_operational_period_report(
    company_id: UUID,
    site_id: UUID,
    period_start: date = Query(...),
    period_end: date = Query(...),
    db: Session = Depends(get_db),
):
    try:
        return build_operational_period_report(
            db,
            company_id=company_id,
            site_id=site_id,
            period_start=period_start,
            period_end=period_end,
        )
    except ValueError as exc:
        status_code = 404 if "據點不存在" in str(exc) else 422
        raise HTTPException(status_code=status_code, detail=str(exc)) from exc
