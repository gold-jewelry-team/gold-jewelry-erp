import re
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db.session import SessionLocal
from app.models.company import Company
from app.models.product import Product, ProductCategory
from app.models.product_code_sequence import ProductCodeSequence
from app.routers.schemas.product_master import (
    ProductCategoryCreate, ProductCategoryRead, ProductCreate,
    ProductRead, ProductUpdate,
)

router = APIRouter(tags=["product-master"])


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def _require_company(db: Session, company_id: UUID) -> None:
    if db.get(Company, company_id) is None:
        raise HTTPException(status_code=404, detail="找不到指定公司。")


def _require_category(db: Session, company_id: UUID, category_id: UUID | None) -> None:
    if category_id is None:
        return
    category = db.scalar(select(ProductCategory).where(
        ProductCategory.id == category_id,
        ProductCategory.company_id == company_id,
    ))
    if category is None:
        raise HTTPException(status_code=404, detail="找不到此公司的商品分類。")
    if not category.is_active:
        raise HTTPException(status_code=422, detail="不可將商品指定至停用中的分類。")


@router.get("/companies/{company_id}/product-categories", response_model=list[ProductCategoryRead])
def list_product_categories(
    company_id: UUID,
    include_inactive: bool = False,
    db: Session = Depends(get_db),
):
    _require_company(db, company_id)
    statement = select(ProductCategory).where(ProductCategory.company_id == company_id)
    if not include_inactive:
        statement = statement.where(ProductCategory.is_active.is_(True))
    return list(db.scalars(statement.order_by(
        ProductCategory.sort_order, ProductCategory.code
    )).all())


@router.post("/companies/{company_id}/product-categories",
             response_model=ProductCategoryRead, status_code=201)
def create_product_category(
    company_id: UUID,
    payload: ProductCategoryCreate,
    db: Session = Depends(get_db),
):
    _require_company(db, company_id)
    if payload.parent_id is not None:
        parent = db.scalar(select(ProductCategory).where(
            ProductCategory.id == payload.parent_id,
            ProductCategory.company_id == company_id,
        ))
        if parent is None:
            raise HTTPException(status_code=404, detail="找不到此公司的上層商品分類。")
        if not parent.is_active:
            raise HTTPException(status_code=422, detail="不可使用停用中的上層分類。")
    category = ProductCategory(company_id=company_id, **payload.model_dump())
    db.add(category)
    try:
        db.commit()
        db.refresh(category)
        return category
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail="商品分類代碼已存在或資料衝突。") from exc


@router.get("/companies/{company_id}/products", response_model=list[ProductRead])
def list_products(
    company_id: UUID,
    category_id: UUID | None = None,
    q: str | None = Query(default=None, min_length=1, max_length=100),
    include_inactive: bool = False,
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
):
    _require_company(db, company_id)
    statement = select(Product).where(Product.company_id == company_id)
    if category_id is not None:
        statement = statement.where(Product.category_id == category_id)
    if not include_inactive:
        statement = statement.where(Product.is_active.is_(True))
    if q:
        term = f"%{q.strip()}%"
        statement = statement.where(or_(
            Product.product_code.ilike(term),
            Product.barcode.ilike(term),
            Product.name.ilike(term),
        ))
    return list(db.scalars(statement.order_by(
        Product.product_code
    ).offset(offset).limit(limit)).all())


@router.post("/companies/{company_id}/products", response_model=ProductRead, status_code=201)
def create_product(
    company_id: UUID,
    payload: ProductCreate,
    db: Session = Depends(get_db),
):
    _require_company(db, company_id)
    _require_category(db, company_id, payload.category_id)
    if payload.net_weight > payload.gross_weight:
        raise HTTPException(status_code=422, detail="淨重不可大於總重。")
    product = Product(company_id=company_id, **payload.model_dump())
    db.add(product)
    # Manual codes also advance the shared company sequence when they end in -digits.
    sequence = db.scalar(
        select(ProductCodeSequence)
        .where(ProductCodeSequence.company_id == company_id)
        .with_for_update()
    )
    match = re.search(r"-(\d+)$", product.product_code)
    if match:
        numeric_suffix = int(match.group(1))
        existing_codes = db.query(Product.product_code).filter(
            Product.company_id == company_id
        ).all()
        if any(
            (existing_match := re.search(r"-(\d+)$", existing_code[0]))
            and int(existing_match.group(1)) == numeric_suffix
            for existing_code in existing_codes
        ):
            raise HTTPException(status_code=409, detail="此流水號已被其他商品使用，請使用下一個未使用號碼。")
        if sequence is not None:
            sequence.next_number = max(sequence.next_number, numeric_suffix + 1)
    try:
        db.commit()
        db.refresh(product)
        return product
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail="商品編號或條碼已存在，請檢查後再試。") from exc


@router.patch("/companies/{company_id}/products/{product_id}", response_model=ProductRead)
def update_product(
    company_id: UUID,
    product_id: UUID,
    payload: ProductUpdate,
    db: Session = Depends(get_db),
):
    _require_company(db, company_id)
    product = db.scalar(select(Product).where(
        Product.id == product_id, Product.company_id == company_id
    ))
    if product is None:
        raise HTTPException(status_code=404, detail="找不到指定商品。")
    changes = payload.model_dump(exclude_unset=True)
    if "product_code" in changes and changes["product_code"] is not None:
        sequence = db.scalar(
            select(ProductCodeSequence)
            .where(ProductCodeSequence.company_id == company_id)
            .with_for_update()
        )
        match = re.search(r"-(\d+)$", changes["product_code"])
        if match:
            numeric_suffix = int(match.group(1))
            existing_codes = db.query(Product.id, Product.product_code).where(
                Product.company_id == company_id,
                Product.id != product_id,
            ).all()
            if any(
                (existing_match := re.search(r"-(\d+)$", existing_code))
                and int(existing_match.group(1)) == numeric_suffix
                for _, existing_code in existing_codes
            ):
                raise HTTPException(status_code=409, detail="此流水號已被其他商品使用，請使用其他未使用號碼。")
            if sequence is not None:
                sequence.next_number = max(sequence.next_number, numeric_suffix + 1)
    if "category_id" in changes:
        _require_category(db, company_id, changes["category_id"])
    gross_weight = changes.get("gross_weight", product.gross_weight)
    net_weight = changes.get("net_weight", product.net_weight)
    if gross_weight is not None and net_weight is not None and net_weight > gross_weight:
        raise HTTPException(status_code=422, detail="淨重不可大於總重。")
    for field, value in changes.items():
        setattr(product, field, value)
    try:
        db.commit()
        db.refresh(product)
        return product
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail="商品編號或條碼已存在，請檢查後再試。") from exc
