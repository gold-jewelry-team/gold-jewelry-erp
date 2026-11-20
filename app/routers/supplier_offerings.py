from datetime import datetime, timezone
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db.session import SessionLocal
from app.models.company import Company
from app.models.product import Product, ProductCategory
from app.models.supplier import Supplier
from app.models.supplier_offering import SupplierCategoryOffering, SupplierProductOffering
from app.routers.schemas.supplier_offerings import (
    SupplierCategoryOfferingCreate, SupplierCategoryOfferingRead,
    SupplierCategoryOfferingUpdate, SupplierProductOfferingCreate,
    SupplierProductOfferingRead, SupplierProductOfferingUpdate,
)

router = APIRouter(tags=["supplier-offerings"])


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def _company_supplier(db: Session, company_id: UUID, supplier_id: UUID) -> Supplier:
    supplier = db.scalar(select(Supplier).where(
        Supplier.id == supplier_id, Supplier.company_id == company_id
    ))
    if supplier is None:
        raise HTTPException(status_code=404, detail="找不到此公司的供應商。")
    return supplier


def _company_product(db: Session, company_id: UUID, product_id: UUID) -> Product:
    product = db.scalar(select(Product).where(
        Product.id == product_id, Product.company_id == company_id
    ))
    if product is None:
        raise HTTPException(status_code=404, detail="找不到此公司的商品。")
    return product


@router.get("/companies/{company_id}/supplier-category-offerings",
            response_model=list[SupplierCategoryOfferingRead])
def list_supplier_category_offerings(
    company_id: UUID,
    supplier_id: UUID | None = None,
    category_id: UUID | None = None,
    include_inactive: bool = False,
    db: Session = Depends(get_db),
):
    if db.get(Company, company_id) is None:
        raise HTTPException(status_code=404, detail="找不到指定公司。")
    statement = select(SupplierCategoryOffering).where(
        SupplierCategoryOffering.company_id == company_id
    )
    if supplier_id:
        statement = statement.where(SupplierCategoryOffering.supplier_id == supplier_id)
    if category_id:
        statement = statement.where(SupplierCategoryOffering.category_id == category_id)
    if not include_inactive:
        statement = statement.where(SupplierCategoryOffering.status == "ACTIVE")
    return list(db.scalars(statement.order_by(
        SupplierCategoryOffering.category_id, SupplierCategoryOffering.is_preferred.desc()
    )).all())


@router.post("/companies/{company_id}/suppliers/{supplier_id}/category-offerings",
             response_model=SupplierCategoryOfferingRead, status_code=201)
def create_supplier_category_offering(
    company_id: UUID, supplier_id: UUID, payload: SupplierCategoryOfferingCreate,
    db: Session = Depends(get_db),
):
    _company_supplier(db, company_id, supplier_id)
    category = db.scalar(select(ProductCategory).where(
        ProductCategory.id == payload.category_id,
        ProductCategory.company_id == company_id,
    ))
    if category is None:
        raise HTTPException(status_code=404, detail="找不到此公司的商品分類。")
    if not category.is_active:
        raise HTTPException(status_code=422, detail="不可將供貨關係指定至停用中的商品分類。")
    offering = SupplierCategoryOffering(
        company_id=company_id, supplier_id=supplier_id, **payload.model_dump()
    )
    if offering.is_preferred:
        db.query(SupplierCategoryOffering).filter(
            SupplierCategoryOffering.company_id == company_id,
            SupplierCategoryOffering.category_id == offering.category_id,
        ).update({SupplierCategoryOffering.is_preferred: False}, synchronize_session=False)
    db.add(offering)
    try:
        db.commit()
        db.refresh(offering)
        return offering
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail="此廠商與商品分類的供貨關係已存在。") from exc


@router.patch("/companies/{company_id}/supplier-category-offerings/{offering_id}",
              response_model=SupplierCategoryOfferingRead)
def update_supplier_category_offering(
    company_id: UUID, offering_id: UUID, payload: SupplierCategoryOfferingUpdate,
    db: Session = Depends(get_db),
):
    offering = db.scalar(select(SupplierCategoryOffering).where(
        SupplierCategoryOffering.id == offering_id,
        SupplierCategoryOffering.company_id == company_id,
    ))
    if offering is None:
        raise HTTPException(status_code=404, detail="找不到供貨分類紀錄。")
    changes = payload.model_dump(exclude_unset=True)
    if changes.get("is_preferred"):
        db.query(SupplierCategoryOffering).filter(
            SupplierCategoryOffering.company_id == company_id,
            SupplierCategoryOffering.category_id == offering.category_id,
            SupplierCategoryOffering.id != offering.id,
        ).update({SupplierCategoryOffering.is_preferred: False}, synchronize_session=False)
    for key, value in changes.items():
        setattr(offering, key, value)
    try:
        db.commit()
        db.refresh(offering)
        return offering
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail="更新供貨分類失敗。") from exc


@router.get("/companies/{company_id}/supplier-product-offerings",
            response_model=list[SupplierProductOfferingRead])
def list_supplier_product_offerings(
    company_id: UUID,
    supplier_id: UUID | None = None,
    product_id: UUID | None = None,
    category_id: UUID | None = None,
    include_inactive: bool = False,
    db: Session = Depends(get_db),
):
    if db.get(Company, company_id) is None:
        raise HTTPException(status_code=404, detail="找不到指定公司。")
    statement = select(SupplierProductOffering).where(
        SupplierProductOffering.company_id == company_id
    )
    if supplier_id:
        statement = statement.where(SupplierProductOffering.supplier_id == supplier_id)
    if product_id:
        statement = statement.where(SupplierProductOffering.product_id == product_id)
    if category_id:
        statement = statement.join(
            Product, Product.id == SupplierProductOffering.product_id
        ).where(Product.category_id == category_id)
    if not include_inactive:
        statement = statement.where(SupplierProductOffering.status == "ACTIVE")
    return list(db.scalars(statement.order_by(
        SupplierProductOffering.supplier_id, SupplierProductOffering.product_id
    )).all())


@router.get("/companies/{company_id}/products/{product_id}/supplier-offerings",
            response_model=list[SupplierProductOfferingRead])
def list_product_supplier_offerings(
    company_id: UUID, product_id: UUID, include_inactive: bool = False,
    db: Session = Depends(get_db),
):
    _company_product(db, company_id, product_id)
    statement = select(SupplierProductOffering).where(
        SupplierProductOffering.company_id == company_id,
        SupplierProductOffering.product_id == product_id,
    )
    if not include_inactive:
        statement = statement.where(SupplierProductOffering.status == "ACTIVE")
    return list(db.scalars(statement.order_by(
        SupplierProductOffering.is_preferred.desc(), SupplierProductOffering.supplier_id
    )).all())


@router.post("/companies/{company_id}/suppliers/{supplier_id}/product-offerings",
             response_model=SupplierProductOfferingRead, status_code=201)
def create_supplier_product_offering(
    company_id: UUID, supplier_id: UUID, payload: SupplierProductOfferingCreate,
    db: Session = Depends(get_db),
):
    _company_supplier(db, company_id, supplier_id)
    product = _company_product(db, company_id, payload.product_id)
    if product.category_id is not None:
        category = db.scalar(select(ProductCategory).where(
            ProductCategory.id == product.category_id,
            ProductCategory.company_id == company_id,
            ProductCategory.is_active.is_(True),
        ))
        if category is None:
            raise HTTPException(status_code=422, detail="商品分類不存在或已停用。")
        category_offering = db.scalar(select(SupplierCategoryOffering).where(
            SupplierCategoryOffering.company_id == company_id,
            SupplierCategoryOffering.supplier_id == supplier_id,
            SupplierCategoryOffering.category_id == product.category_id,
        ))
        if category_offering is None:
            db.add(SupplierCategoryOffering(
                company_id=company_id, supplier_id=supplier_id,
                category_id=product.category_id, status="ACTIVE",
            ))
    offering = SupplierProductOffering(
        company_id=company_id, supplier_id=supplier_id,
        last_quoted_at=datetime.now(timezone.utc), **payload.model_dump()
    )
    if offering.is_preferred:
        db.query(SupplierProductOffering).filter(
            SupplierProductOffering.company_id == company_id,
            SupplierProductOffering.product_id == offering.product_id,
        ).update({SupplierProductOffering.is_preferred: False}, synchronize_session=False)
    db.add(offering)
    try:
        db.commit()
        db.refresh(offering)
        return offering
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail="此廠商與商品的供貨關係已存在。") from exc


@router.patch("/companies/{company_id}/supplier-product-offerings/{offering_id}",
              response_model=SupplierProductOfferingRead)
def update_supplier_product_offering(
    company_id: UUID, offering_id: UUID, payload: SupplierProductOfferingUpdate,
    db: Session = Depends(get_db),
):
    offering = db.scalar(select(SupplierProductOffering).where(
        SupplierProductOffering.id == offering_id,
        SupplierProductOffering.company_id == company_id,
    ))
    if offering is None:
        raise HTTPException(status_code=404, detail="找不到廠商商品供貨紀錄。")
    changes = payload.model_dump(exclude_unset=True)
    if changes.get("quoted_unit_cost") is not None or changes.get("currency_code") is not None:
        offering.last_quoted_at = datetime.now(timezone.utc)
    if changes.get("is_preferred"):
        db.query(SupplierProductOffering).filter(
            SupplierProductOffering.company_id == company_id,
            SupplierProductOffering.product_id == offering.product_id,
            SupplierProductOffering.id != offering.id,
        ).update({SupplierProductOffering.is_preferred: False}, synchronize_session=False)
    for key, value in changes.items():
        setattr(offering, key, value)
    try:
        db.commit()
        db.refresh(offering)
        return offering
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail="更新廠商商品供貨紀錄失敗。") from exc
