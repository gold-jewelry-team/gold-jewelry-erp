"""Company-scoped default jewelry categories."""
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.product import ProductCategory

DEFAULT_PRODUCT_CATEGORIES = (
    ("PAIR_RING", "對戒", 10),
    ("WOMENS_RING", "女戒", 20),
    ("ADJUSTABLE_PINKY_RING", "可調式尾戒", 30),
    ("FIXED_PINKY_RING", "固定圍尾戒", 40),
    ("OPEN_BRACELET", "開口式手環", 50),
    ("FIXED_BRACELET", "固定圍手環", 60),
    ("WOMENS_PENDANT", "女墜", 70),
    ("MENS_PENDANT", "男墜", 80),
    ("WOMENS_CHAIN_BRACELET", "女手鏈", 90),
    ("MENS_CHAIN_BRACELET", "男手鏈", 100),
    ("RED_STRING", "紅線", 110),
    ("EARRINGS", "耳環", 120),
    ("NECKLACE_SET", "套鏈", 130),
    ("CHILD_BRACELET", "童手環", 140),
    ("GOLD_NUGGET", "小金塊", 150),
)


def ensure_default_product_categories(session: Session, company_id: UUID) -> None:
    existing = set(session.scalars(
        select(ProductCategory.code).where(ProductCategory.company_id == company_id)
    ).all())
    for code, name, sort_order in DEFAULT_PRODUCT_CATEGORIES:
        if code not in existing:
            session.add(ProductCategory(
                company_id=company_id, code=code, name=name, sort_order=sort_order
            ))
