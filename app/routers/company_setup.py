from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db.session import SessionLocal
from app.models.company import Company
from app.models.site import Site
from app.models.storage_location import StorageLocation
from app.models.product_code_sequence import ProductCodeSequence
from app.routers.schemas.company_setup import (
    CompanyCreate, CompanyRead, SiteCreate, SiteRead,
    StorageLocationCreate, StorageLocationRead,
)

router = APIRouter(tags=["company-setup"])


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


@router.get("/companies", response_model=list[CompanyRead])
def list_companies(include_inactive: bool = False, db: Session = Depends(get_db)):
    statement = select(Company)
    if not include_inactive:
        statement = statement.where(Company.is_active.is_(True))
    return list(db.scalars(statement.order_by(Company.code)).all())


@router.post("/companies", response_model=CompanyRead, status_code=201)
def create_company(payload: CompanyCreate, db: Session = Depends(get_db)):
    company = Company(**payload.model_dump())
    db.add(company)
    try:
        db.flush()
        db.add(ProductCodeSequence(company_id=company.id, next_number=1, number_width=5))
        db.commit()
        db.refresh(company)
        return company
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail="公司代碼已存在或資料衝突。") from exc


@router.get("/companies/{company_id}/sites", response_model=list[SiteRead])
def list_sites(company_id: UUID, include_inactive: bool = False, db: Session = Depends(get_db)):
    if db.get(Company, company_id) is None:
        raise HTTPException(status_code=404, detail="找不到指定公司。")
    statement = select(Site).where(Site.company_id == company_id)
    if not include_inactive:
        statement = statement.where(Site.is_active.is_(True))
    return list(db.scalars(statement.order_by(Site.code)).all())


@router.post("/companies/{company_id}/sites", response_model=SiteRead, status_code=201)
def create_site(company_id: UUID, payload: SiteCreate, db: Session = Depends(get_db)):
    if db.get(Company, company_id) is None:
        raise HTTPException(status_code=404, detail="找不到指定公司。")
    site = Site(company_id=company_id, **payload.model_dump())
    db.add(site)
    try:
        db.commit()
        db.refresh(site)
        return site
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail="據點代碼已存在或資料衝突。") from exc


@router.get("/companies/{company_id}/sites/{site_id}/storage-locations", response_model=list[StorageLocationRead])
def list_storage_locations(company_id: UUID, site_id: UUID, include_inactive: bool = False,
                           db: Session = Depends(get_db)):
    site = db.scalar(select(Site).where(Site.id == site_id, Site.company_id == company_id))
    if site is None:
        raise HTTPException(status_code=404, detail="找不到指定據點。")
    statement = select(StorageLocation).where(StorageLocation.site_id == site_id)
    if not include_inactive:
        statement = statement.where(StorageLocation.is_active.is_(True))
    return list(db.scalars(statement.order_by(StorageLocation.code)).all())


@router.post("/companies/{company_id}/sites/{site_id}/storage-locations",
             response_model=StorageLocationRead, status_code=201)
def create_storage_location(company_id: UUID, site_id: UUID, payload: StorageLocationCreate,
                            db: Session = Depends(get_db)):
    site = db.scalar(select(Site).where(Site.id == site_id, Site.company_id == company_id))
    if site is None:
        raise HTTPException(status_code=404, detail="找不到指定據點。")
    location = StorageLocation(site_id=site_id, **payload.model_dump())
    db.add(location)
    try:
        db.commit()
        db.refresh(location)
        return location
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail="儲存位置代碼已存在或資料衝突。") from exc
