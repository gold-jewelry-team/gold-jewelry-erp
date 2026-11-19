from datetime import datetime, timezone
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.db.session import SessionLocal
from app.models.company import Company
from app.routers.schemas.gold_price import GoldPriceCreate, GoldPriceRead
from app.services.pricing.gold_price_management import create_gold_price, list_gold_prices
from app.services.pricing.gold_prices import get_effective_gold_price

router = APIRouter(prefix="/companies/{company_id}/gold-prices", tags=["gold-prices"])


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


@router.get("", response_model=list[GoldPriceRead])
def get_gold_price_history(
    company_id: UUID,
    site_id: UUID | None = None,
    price_type: str | None = Query(default=None, pattern="^(BUY|SELL)$"),
    limit: int = Query(default=100, ge=1, le=500),
    db: Session = Depends(get_db),
):
    if db.get(Company, company_id) is None:
        raise HTTPException(status_code=404, detail="找不到指定公司。")
    try:
        return list_gold_prices(
            db, company_id=company_id, site_id=site_id,
            price_type=price_type, limit=limit,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get("/effective", response_model=GoldPriceRead | None)
def get_effective_price(
    company_id: UUID,
    at: datetime = Query(default_factory=lambda: datetime.now(timezone.utc)),
    site_id: UUID | None = None,
    price_type: str = Query(pattern="^(BUY|SELL)$"),
    db: Session = Depends(get_db),
):
    if db.get(Company, company_id) is None:
        raise HTTPException(status_code=404, detail="找不到指定公司。")
    return get_effective_gold_price(
        db, company_id=company_id, site_id=site_id,
        price_type=price_type, at=at,
    )


@router.post("", response_model=GoldPriceRead, status_code=201)
def post_gold_price(
    company_id: UUID,
    payload: GoldPriceCreate,
    db: Session = Depends(get_db),
):
    try:
        price = create_gold_price(
            db, company_id=company_id, **payload.model_dump()
        )
        db.commit()
        db.refresh(price)
        return price
    except ValueError as exc:
        db.rollback()
        if "找不到指定公司" in str(exc):
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except Exception:
        db.rollback()
        raise
