from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db.session import SessionLocal
from app.models.company import Company
from app.models.inventory import InventoryMovement
from app.models.site import Site
from app.models.storage_location import StorageLocation
from app.models.product_code_sequence import ProductCodeSequence
from app.services.default_product_categories import ensure_default_product_categories
from app.services.access_control import ensure_company_system_roles
from app.routers.schemas.company_setup import (
    CompanyCreate, CompanyRead, CompanyUpdate, SiteCreate, SiteRead, SiteUpdate,
    StorageLocationCreate, StorageLocationRead, StorageLocationUpdate,
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
        ensure_default_product_categories(db, company.id)
        ensure_company_system_roles(db, company.id)
        db.commit()
        db.refresh(company)
        return company
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail="公司代碼已存在或資料衝突。") from exc


@router.patch("/companies/{company_id}", response_model=CompanyRead)
def update_company(company_id: UUID, payload: CompanyUpdate, db: Session = Depends(get_db)):
    company = db.get(Company, company_id)
    if company is None:
        raise HTTPException(status_code=404, detail="找不到指定公司。")
    changes = payload.model_dump(exclude_unset=True)
    if any(changes.get(field) is None for field in ("code", "name") if field in changes):
        raise HTTPException(status_code=422, detail="公司代碼與名稱不可為空。")
    if "is_active" in changes and changes["is_active"] is None:
        raise HTTPException(status_code=422, detail="公司啟用狀態不可為空。")
    if changes.get("is_active") is False and company.is_active:
        active_site = db.scalar(select(Site.id).where(
            Site.company_id == company_id, Site.is_active.is_(True)
        ).limit(1))
        if active_site is not None:
            raise HTTPException(status_code=409, detail="此公司仍有啟用中的據點，請先停用據點。")
    for key, value in changes.items():
        setattr(company, key, value)
    try:
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
    company = db.get(Company, company_id)
    if company is None:
        raise HTTPException(status_code=404, detail="找不到指定公司。")
    if not company.is_active:
        raise HTTPException(status_code=422, detail="不可在停用中的公司建立據點。")
    site = Site(company_id=company_id, **payload.model_dump())
    db.add(site)
    try:
        db.commit()
        db.refresh(site)
        return site
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail="據點代碼已存在或資料衝突。") from exc


@router.patch("/companies/{company_id}/sites/{site_id}", response_model=SiteRead)
def update_site(company_id: UUID, site_id: UUID, payload: SiteUpdate, db: Session = Depends(get_db)):
    company = db.get(Company, company_id)
    if company is None:
        raise HTTPException(status_code=404, detail="找不到指定公司。")
    site = db.scalar(select(Site).where(Site.id == site_id, Site.company_id == company_id))
    if site is None:
        raise HTTPException(status_code=404, detail="找不到指定據點。")
    changes = payload.model_dump(exclude_unset=True)
    if any(changes.get(field) is None for field in ("code", "name") if field in changes):
        raise HTTPException(status_code=422, detail="據點代碼與名稱不可為空。")
    if "is_active" in changes and changes["is_active"] is None:
        raise HTTPException(status_code=422, detail="據點啟用狀態不可為空。")
    if changes.get("is_active") is True and not company.is_active:
        raise HTTPException(status_code=422, detail="請先重新啟用公司。")
    if changes.get("is_active") is False and site.is_active:
        active_location = db.scalar(select(StorageLocation.id).where(
            StorageLocation.site_id == site_id, StorageLocation.is_active.is_(True)
        ).limit(1))
        if active_location is not None:
            raise HTTPException(status_code=409, detail="此據點仍有啟用中的儲存位置，請先停用儲存位置。")
        locations = list(db.scalars(select(StorageLocation).where(StorageLocation.site_id == site_id)).all())
        if any(_location_has_stock(db, company_id, site_id, location.id) for location in locations):
            raise HTTPException(status_code=409, detail="此據點仍有庫存，無法停用。")
    for key, value in changes.items():
        setattr(site, key, value)
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


def _location_has_stock(db: Session, company_id: UUID, site_id: UUID, location_id: UUID) -> bool:
    rows = db.execute(select(
        InventoryMovement.product_id,
        InventoryMovement.quantity,
        InventoryMovement.from_location_id,
        InventoryMovement.to_location_id,
    ).where(
        InventoryMovement.company_id == company_id,
        InventoryMovement.site_id == site_id,
        or_(
            InventoryMovement.from_location_id == location_id,
            InventoryMovement.to_location_id == location_id,
        ),
    )).all()
    balances = {}
    for product_id, quantity, from_location_id, to_location_id in rows:
        balances[product_id] = balances.get(product_id, 0) + (
            quantity if to_location_id == location_id else 0
        ) - (
            quantity if from_location_id == location_id else 0
        )
    return any(balance != 0 for balance in balances.values())


@router.patch("/companies/{company_id}/sites/{site_id}/storage-locations/{location_id}", response_model=StorageLocationRead)
def update_storage_location(
    company_id: UUID, site_id: UUID, location_id: UUID,
    payload: StorageLocationUpdate, db: Session = Depends(get_db),
):
    company = db.get(Company, company_id)
    if company is None:
        raise HTTPException(status_code=404, detail="找不到指定公司。")
    site = db.scalar(select(Site).where(Site.id == site_id, Site.company_id == company_id))
    if site is None:
        raise HTTPException(status_code=404, detail="找不到指定據點。")
    location = db.scalar(select(StorageLocation).where(
        StorageLocation.id == location_id, StorageLocation.site_id == site_id
    ))
    if location is None:
        raise HTTPException(status_code=404, detail="找不到指定儲存位置。")
    changes = payload.model_dump(exclude_unset=True)
    if any(changes.get(field) is None for field in ("code", "name", "location_type") if field in changes):
        raise HTTPException(status_code=422, detail="位置代碼、名稱與類型不可為空。")
    if "is_active" in changes and changes["is_active"] is None:
        raise HTTPException(status_code=422, detail="儲存位置啟用狀態不可為空。")
    if changes.get("is_active") is True and (not company.is_active or not site.is_active):
        raise HTTPException(status_code=422, detail="請先重新啟用公司與據點。")
    if changes.get("is_active") is False and location.is_active:
        if _location_has_stock(db, company_id, site_id, location_id):
            raise HTTPException(status_code=409, detail="此儲存位置仍有庫存，請先移出所有商品再停用。")
    for key, value in changes.items():
        setattr(location, key, value)
    try:
        db.commit()
        db.refresh(location)
        return location
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail="儲存位置代碼已存在或資料衝突。") from exc


@router.post("/companies/{company_id}/sites/{site_id}/storage-locations",
             response_model=StorageLocationRead, status_code=201)
def create_storage_location(company_id: UUID, site_id: UUID, payload: StorageLocationCreate,
                            db: Session = Depends(get_db)):
    site = db.scalar(select(Site).where(Site.id == site_id, Site.company_id == company_id))
    if site is None:
        raise HTTPException(status_code=404, detail="找不到指定據點。")
    company = db.get(Company, company_id)
    if company is None or not company.is_active or not site.is_active:
        raise HTTPException(status_code=422, detail="請先啟用公司與據點，再建立儲存位置。")
    location = StorageLocation(site_id=site_id, **payload.model_dump())
    db.add(location)
    try:
        db.commit()
        db.refresh(location)
        return location
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail="儲存位置代碼已存在或資料衝突。") from exc
