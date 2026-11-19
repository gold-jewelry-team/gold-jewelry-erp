import re
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.session import SessionLocal
from app.models.company import Company
from app.models.product import Product
from app.models.product_code_sequence import ProductCodeSequence
from app.routers.schemas.product_code_sequence import (
    ProductCodeGenerate, ProductCodeGenerated, ProductCodeSequenceRead,
    ProductCodeSequenceUpdate,
)

router = APIRouter(tags=["product-code-sequence"])


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def _require_company(db: Session, company_id: UUID) -> None:
    if db.get(Company, company_id) is None:
        raise HTTPException(status_code=404, detail="找不到指定公司。")


def _get_sequence(db: Session, company_id: UUID, *, lock: bool = False) -> ProductCodeSequence:
    statement = select(ProductCodeSequence).where(
        ProductCodeSequence.company_id == company_id
    )
    if lock:
        statement = statement.with_for_update()
    sequence = db.scalar(statement)
    if sequence is None:
        sequence = ProductCodeSequence(company_id=company_id, next_number=1, number_width=5)
        db.add(sequence)
        db.flush()
    return sequence


def _largest_existing_suffix(db: Session, company_id: UUID) -> int:
    largest = 0
    for code, in db.query(Product.product_code).filter(Product.company_id == company_id).all():
        match = re.search(r"-(\d+)$", code)
        if match:
            largest = max(largest, int(match.group(1)))
    return largest


@router.get(
    "/companies/{company_id}/product-code-sequence",
    response_model=ProductCodeSequenceRead,
)
def read_product_code_sequence(company_id: UUID, db: Session = Depends(get_db)):
    _require_company(db, company_id)
    sequence = _get_sequence(db, company_id)
    db.commit()
    db.refresh(sequence)
    return sequence


@router.patch(
    "/companies/{company_id}/product-code-sequence",
    response_model=ProductCodeSequenceRead,
)
def update_product_code_sequence(
    company_id: UUID,
    payload: ProductCodeSequenceUpdate,
    db: Session = Depends(get_db),
):
    _require_company(db, company_id)
    sequence = _get_sequence(db, company_id, lock=True)
    changes = payload.model_dump(exclude_unset=True)
    for field, value in changes.items():
        setattr(sequence, field, value)
    db.commit()
    db.refresh(sequence)
    return sequence


@router.post(
    "/companies/{company_id}/product-code-sequence/next",
    response_model=ProductCodeGenerated,
)
def generate_product_code(
    company_id: UUID,
    payload: ProductCodeGenerate,
    db: Session = Depends(get_db),
):
    _require_company(db, company_id)
    sequence = _get_sequence(db, company_id, lock=True)
    prefix = payload.prefix.upper()
    used_numbers = {
        int(match.group(1))
        for code, in db.query(Product.product_code).filter(
            Product.company_id == company_id
        ).all()
        if (match := re.search(r"-(\d+)$", code))
    }
    while sequence.next_number in used_numbers:
        sequence.next_number += 1
    code = f"{prefix}{sequence.next_number:0{sequence.number_width}d}"
    sequence.next_number += 1
    db.commit()
    return ProductCodeGenerated(product_code=code, next_number=sequence.next_number)
