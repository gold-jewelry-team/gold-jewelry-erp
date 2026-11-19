"""Purchase order creation, lifecycle and atomic goods receiving."""
from datetime import date
from decimal import Decimal, ROUND_HALF_UP
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.company import Company
from app.models.inventory import InventoryMovement
from app.models.product import Product
from app.models.purchase import Purchase, PurchaseLine
from app.models.site import Site
from app.models.storage_location import StorageLocation
from app.models.supplier import Supplier


def create_purchase(session: Session, *, company_id: UUID, site_id: UUID, supplier_id: UUID,
                    purchase_no: str, order_date: date, expected_date: date | None,
                    currency_code: str, note: str | None, lines: list[dict]) -> Purchase:
    company = session.get(Company, company_id)
    site = session.get(Site, site_id)
    supplier = session.get(Supplier, supplier_id)
    if company is None:
        raise ValueError("找不到指定公司。")
    if site is None or site.company_id != company_id:
        raise ValueError("據點不存在或不屬於指定公司。")
    if supplier is None or supplier.company_id != company_id or not supplier.is_active:
        raise ValueError("供應商不存在、未啟用或不屬於指定公司。")
    if not lines:
        raise ValueError("採購單至少需要一筆商品明細。")
    if len(currency_code) != 3:
        raise ValueError("幣別必須使用三碼代碼。")

    product_ids = {item["product_id"] for item in lines}
    products = {p.id: p for p in session.scalars(select(Product).where(Product.id.in_(product_ids))).all()}
    if len(products) != len(product_ids):
        raise ValueError("部分商品不存在。")
    if any(p.company_id != company_id or not p.is_active for p in products.values()):
        raise ValueError("採購商品未啟用或不屬於指定公司。")

    purchase = Purchase(
        company_id=company_id, site_id=site_id, supplier_id=supplier_id,
        purchase_no=purchase_no, order_date=order_date, expected_date=expected_date,
        currency_code=currency_code.upper(), note=note, status="DRAFT",
    )
    session.add(purchase)
    session.flush()
    for item in lines:
        session.add(PurchaseLine(purchase_id=purchase.id, **item))
    session.flush()
    return purchase


def submit_purchase(session: Session, *, purchase_id: UUID) -> Purchase:
    purchase = session.execute(select(Purchase).where(Purchase.id == purchase_id).with_for_update()).scalar_one_or_none()
    if purchase is None:
        raise ValueError("找不到採購單。")
    if purchase.status != "DRAFT":
        raise ValueError("只有草稿採購單可以送出。")
    if not session.scalar(select(PurchaseLine.id).where(PurchaseLine.purchase_id == purchase_id).limit(1)):
        raise ValueError("採購單沒有商品明細。")
    purchase.status = "ORDERED"
    session.flush()
    return purchase


def cancel_purchase(session: Session, *, purchase_id: UUID) -> Purchase:
    purchase = session.execute(select(Purchase).where(Purchase.id == purchase_id).with_for_update()).scalar_one_or_none()
    if purchase is None:
        raise ValueError("找不到採購單。")
    if purchase.status not in {"DRAFT", "ORDERED"}:
        raise ValueError("只有草稿或尚未收貨的採購單可以取消。")
    purchase.status = "CANCELLED"
    session.flush()
    return purchase


def receive_purchase_line(session: Session, *, purchase_id: UUID, purchase_line_id: UUID,
                          location_id: UUID, received_quantity: Decimal) -> InventoryMovement:
    if not isinstance(received_quantity, Decimal) or received_quantity <= 0:
        raise ValueError("本次驗收數量必須是正數 Decimal。")
    purchase = session.execute(select(Purchase).where(Purchase.id == purchase_id).with_for_update()).scalar_one_or_none()
    if purchase is None:
        raise ValueError("找不到採購單。")
    if purchase.status not in {"ORDERED", "PARTIALLY_RECEIVED"}:
        raise ValueError("只有已下單或部分到貨的採購單可以驗收。")
    line = session.execute(select(PurchaseLine).where(
        PurchaseLine.id == purchase_line_id, PurchaseLine.purchase_id == purchase_id
    ).with_for_update()).scalar_one_or_none()
    if line is None:
        raise ValueError("採購明細不存在。")
    if line.received_quantity + received_quantity > line.quantity:
        raise ValueError("本次驗收數量超過尚未到貨數量。")

    supplier = session.get(Supplier, purchase.supplier_id)
    site = session.get(Site, purchase.site_id)
    company = session.get(Company, purchase.company_id)
    product = session.execute(
        select(Product).where(Product.id == line.product_id).with_for_update()
    ).scalar_one_or_none()
    location = session.get(StorageLocation, location_id)
    if company is None or supplier is None or supplier.company_id != purchase.company_id:
        raise ValueError("供應商不存在或不屬於採購單公司。")
    if site is None or site.company_id != purchase.company_id:
        raise ValueError("採購據點不存在或不屬於採購單公司。")
    if product is None or product.company_id != purchase.company_id:
        raise ValueError("商品不存在或不屬於採購單公司。")
    if location is None or location.site_id != purchase.site_id or not location.is_active:
        raise ValueError("入庫儲存位置不存在、未啟用或不屬於採購據點。")

    receipt_weight = None
    if line.weight is not None:
        previous_weights = session.scalars(select(InventoryMovement.weight).where(
            InventoryMovement.reference_type == "PURCHASE_LINE",
            InventoryMovement.reference_id == line.id,
            InventoryMovement.movement_type == "RECEIPT",
        )).all()
        previously_received_weight = sum(
            (value or Decimal("0") for value in previous_weights), Decimal("0")
        )
        if line.received_quantity + received_quantity == line.quantity:
            receipt_weight = line.weight - previously_received_weight
        else:
            receipt_weight = (
                line.weight * received_quantity / line.quantity
            ).quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP)

    movement = InventoryMovement(
        company_id=purchase.company_id, site_id=purchase.site_id, product_id=line.product_id,
        movement_type="RECEIPT", to_location_id=location_id, quantity=received_quantity,
        weight=receipt_weight, weight_unit_code=line.weight_unit_code,
        reference_type="PURCHASE_LINE", reference_id=line.id,
        note=f"採購單 {purchase.purchase_no} 驗收入庫",
    )
    line.received_quantity += received_quantity
    session.add(movement)
    session.flush()
    lines = session.scalars(select(PurchaseLine).where(PurchaseLine.purchase_id == purchase_id)).all()
    if all(item.received_quantity == item.quantity for item in lines):
        purchase.status = "RECEIVED"
    elif any(item.received_quantity > 0 for item in lines):
        purchase.status = "PARTIALLY_RECEIVED"
    return movement
