import re
from uuid import UUID

from io import BytesIO

import segno
import barcode as linear_barcode
from barcode.writer import SVGWriter
from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import Response
from sqlalchemy import or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db.session import SessionLocal
from app.models.company import Company
from app.models.inventory import InventoryMovement
from app.models.purchase import Purchase, PurchaseLine
from app.models.storage_location import StorageLocation
from app.models.supplier import Supplier
from app.models.product import Product, ProductCategory
from app.models.product_code_sequence import ProductCodeSequence
from app.routers.schemas.product_master import (
    ProductCategoryCreate, ProductCategoryRead, ProductCreate,
    ProductLabelLotRead, ProductRead, ProductUpdate,
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
    db.add(product)
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


@router.get("/companies/{company_id}/products/lookup", response_model=ProductRead)
def lookup_product_by_scan_code(
    company_id: UUID,
    code: str = Query(min_length=1, max_length=100),
    include_inactive: bool = False,
    db: Session = Depends(get_db),
):
    """Resolve one scanned barcode or product code within the selected company."""
    _require_company(db, company_id)
    scanned = code.strip()
    if not scanned:
        raise HTTPException(status_code=422, detail="請提供商品條碼或商品編號。")
    statement = select(Product).where(
        Product.company_id == company_id,
        or_(Product.barcode == scanned, Product.product_code == scanned),
    )
    if not include_inactive:
        statement = statement.where(Product.is_active.is_(True))
    product = db.scalar(statement)
    if product is None:
        raise HTTPException(status_code=404, detail="找不到此條碼／商品編號的有效商品。")
    return product



@router.get("/companies/{company_id}/products/{product_id}/qr.svg", include_in_schema=False)
def product_qr_label(company_id: UUID, product_id: UUID, db: Session = Depends(get_db)):
    """Render a printable QR code containing this item's exact scan identifier."""
    _require_company(db, company_id)
    product = db.scalar(select(Product).where(
        Product.id == product_id, Product.company_id == company_id
    ))
    if product is None:
        raise HTTPException(status_code=404, detail="找不到指定商品。")
    payload = (product.barcode or product.product_code).strip()
    qr = segno.make_qr(payload, error="m")
    output = BytesIO()
    qr.save(output, kind="svg", xmldecl=False, svgns=True, scale=5, border=2)
    return Response(
        content=output.getvalue().decode("utf-8"),
        media_type="image/svg+xml",
        headers={"Cache-Control": "private, max-age=300"},
    )



@router.get("/companies/{company_id}/products/{product_id}/barcode.svg", include_in_schema=False)
def product_linear_barcode(company_id: UUID, product_id: UUID, db: Session = Depends(get_db)):
    """Render a Code 128 barcode using the item's barcode or product code."""
    _require_company(db, company_id)
    product = db.scalar(select(Product).where(
        Product.id == product_id, Product.company_id == company_id
    ))
    if product is None:
        raise HTTPException(status_code=404, detail="找不到指定商品。")
    payload = (product.barcode or product.product_code).strip()
    if not payload.isascii():
        raise HTTPException(status_code=422, detail="條碼內容必須使用 ASCII 字元。")
    try:
        code = linear_barcode.Code128(payload, writer=SVGWriter())
        output = BytesIO()
        code.write(output, options={
            "module_width": 0.18, "module_height": 9, "quiet_zone": 1,
            "font_size": 0, "text_distance": 0, "write_text": False,
        })
    except Exception as exc:
        raise HTTPException(status_code=422, detail="無法產生此商品的一維條碼。") from exc
    return Response(
        content=output.getvalue().decode("utf-8"),
        media_type="image/svg+xml",
        headers={"Cache-Control": "private, max-age=300"},
    )


@router.get(
    "/companies/{company_id}/products/{product_id}/label-lots",
    response_model=list[ProductLabelLotRead],
)
def list_product_label_lots(
    company_id: UUID,
    product_id: UUID,
    limit: int = Query(default=100, ge=1, le=500),
    db: Session = Depends(get_db),
):
    """List actual receipt lots so label printing never guesses supplier or location."""
    _require_company(db, company_id)
    product = db.scalar(select(Product).where(
        Product.id == product_id, Product.company_id == company_id
    ))
    if product is None:
        raise HTTPException(status_code=404, detail="找不到指定商品。")

    statement = (
        select(InventoryMovement, PurchaseLine, Purchase, Supplier, StorageLocation)
        .join(PurchaseLine, PurchaseLine.id == InventoryMovement.reference_id)
        .join(Purchase, Purchase.id == PurchaseLine.purchase_id)
        .join(Supplier, Supplier.id == Purchase.supplier_id)
        .join(StorageLocation, StorageLocation.id == InventoryMovement.to_location_id)
        .where(
            InventoryMovement.company_id == company_id,
            InventoryMovement.product_id == product_id,
            InventoryMovement.movement_type == "RECEIPT",
            or_(
                InventoryMovement.reference_type == "PURCHASE_LINE",
                InventoryMovement.reference_type.like("PR-%"),
            ),
            Purchase.company_id == company_id,
        )
        .order_by(InventoryMovement.occurred_at.desc(), InventoryMovement.created_at.desc())
        .limit(limit)
    )
    result = []
    for movement, line, purchase, supplier, location in db.execute(statement).all():
        result.append(ProductLabelLotRead(
            receipt_id=movement.id,
            purchase_id=purchase.id,
            purchase_no=purchase.purchase_no,
            supplier_code=supplier.code,
            supplier_name=supplier.name,
            location_code=location.code,
            location_name=location.name,
            received_at=movement.occurred_at,
            received_quantity=movement.quantity,
            weight=movement.weight,
            weight_unit_code=movement.weight_unit_code,
            unit_cost=line.unit_cost,
            cost_labor_fee=line.cost_labor_fee,
            currency_code=purchase.currency_code,
        ))
    return result
