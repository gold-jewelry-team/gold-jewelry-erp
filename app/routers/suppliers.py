from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db.session import SessionLocal
from app.models.company import Company
from app.models.supplier import Supplier
from app.routers.schemas.purchasing import SupplierCreate, SupplierRead, SupplierUpdate

router = APIRouter(prefix="/companies/{company_id}/suppliers", tags=["suppliers"])


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


@router.get("", response_model=list[SupplierRead])
def list_suppliers(company_id: UUID, include_inactive: bool = False,
                   limit: int = Query(default=100, ge=1, le=500),
                   db: Session = Depends(get_db)):
    if db.get(Company, company_id) is None:
        raise HTTPException(status_code=404, detail="找不到指定公司。")
    statement = select(Supplier).where(Supplier.company_id == company_id)
    if not include_inactive:
        statement = statement.where(Supplier.is_active.is_(True))
    return list(db.scalars(statement.order_by(Supplier.code).limit(limit)).all())


@router.post("", response_model=SupplierRead, status_code=201)
def create_supplier(company_id: UUID, payload: SupplierCreate, db: Session = Depends(get_db)):
    if db.get(Company, company_id) is None:
        raise HTTPException(status_code=404, detail="找不到指定公司。")
    supplier = Supplier(company_id=company_id, **payload.model_dump())
    db.add(supplier)
    try:
        db.commit()
        db.refresh(supplier)
        return supplier
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail="供應商代碼已存在。") from exc


@router.get("/{supplier_id}", response_model=SupplierRead)
def get_supplier(company_id: UUID, supplier_id: UUID, db: Session = Depends(get_db)):
    supplier = db.scalar(select(Supplier).where(
        Supplier.id == supplier_id, Supplier.company_id == company_id
    ))
    if supplier is None:
        raise HTTPException(status_code=404, detail="找不到指定供應商。")
    return supplier


@router.patch("/{supplier_id}", response_model=SupplierRead)
def update_supplier(company_id: UUID, supplier_id: UUID, payload: SupplierUpdate,
                    db: Session = Depends(get_db)):
    supplier = db.scalar(select(Supplier).where(
        Supplier.id == supplier_id, Supplier.company_id == company_id
    ))
    if supplier is None:
        raise HTTPException(status_code=404, detail="找不到指定供應商。")
    for key, value in payload.model_dump(exclude_unset=True).items():
        setattr(supplier, key, value)
    try:
        db.commit()
        db.refresh(supplier)
        return supplier
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail="供應商代碼已存在或資料不合法。") from exc


@router.post("/{supplier_id}/deactivate", response_model=SupplierRead)
def deactivate_supplier(company_id: UUID, supplier_id: UUID, db: Session = Depends(get_db)):
    supplier = db.scalar(select(Supplier).where(
        Supplier.id == supplier_id, Supplier.company_id == company_id
    ))
    if supplier is None:
        raise HTTPException(status_code=404, detail="找不到指定供應商。")
    supplier.is_active = False
    db.commit()
    db.refresh(supplier)
    return supplier
