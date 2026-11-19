"""Purchase order creation and atomic goods receiving."""
from decimal import Decimal
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


def receive_purchase_line(
    session: Session,
    *,
    purchase_id: UUID,
    purchase_line_id: UUID,
    location_id: UUID,
    received_quantity: Decimal,
) -> InventoryMovement:
    """Receive goods once, atomically updating line totals and inventory ledger."""
    if not isinstance(received_quantity, Decimal) or received_quantity <= 0:
        raise ValueError("本次驗收數量必須是正數 Decimal。")

    purchase = session.execute(
        select(Purchase).where(Purchase.id == purchase_id).with_for_update()
    ).scalar_one_or_none()
    if purchase is None:
        raise ValueError("找不到採購單。")
    if purchase.status not in {"ORDERED", "PARTIALLY_RECEIVED"}:
        raise ValueError("只有已下單或部分到貨的採購單可以驗收。")

    line = session.execute(
        select(PurchaseLine).where(
            PurchaseLine.id == purchase_line_id,
            PurchaseLine.purchase_id == purchase_id,
        ).with_for_update()
    ).scalar_one_or_none()
    if line is None:
        raise ValueError("採購明細不存在。")
    if line.received_quantity + received_quantity > line.quantity:
        raise ValueError("本次驗收數量超過尚未到貨數量。")

    supplier = session.get(Supplier, purchase.supplier_id)
    site = session.get(Site, purchase.site_id)
    company = session.get(Company, purchase.company_id)
    product = session.get(Product, line.product_id)
    location = session.get(StorageLocation, location_id)
    if company is None or supplier is None or supplier.company_id != purchase.company_id:
        raise ValueError("供應商不存在或不屬於採購單公司。")
    if site is None or site.company_id != purchase.company_id:
        raise ValueError("採購據點不存在或不屬於採購單公司。")
    if product is None or product.company_id != purchase.company_id:
        raise ValueError("商品不存在或不屬於採購單公司。")
    if location is None or location.site_id != purchase.site_id:
        raise ValueError("入庫儲存位置不存在或不屬於採購據點。")

    movement = InventoryMovement(
        company_id=purchase.company_id,
        site_id=purchase.site_id,
        product_id=line.product_id,
        movement_type="RECEIPT",
        to_location_id=location_id,
        quantity=received_quantity,
        weight=line.weight,
        weight_unit_code=line.weight_unit_code,
        reference_type="PURCHASE_LINE",
        reference_id=line.id,
        note=f"採購單 {purchase.purchase_no} 驗收入庫",
    )
    line.received_quantity += received_quantity
    session.add(movement)
    session.flush()

    lines = session.scalars(
        select(PurchaseLine).where(PurchaseLine.purchase_id == purchase_id)
    ).all()
    if all(item.received_quantity == item.quantity for item in lines):
        purchase.status = "RECEIVED"
    elif any(item.received_quantity > 0 for item in lines):
        purchase.status = "PARTIALLY_RECEIVED"
    return movement
