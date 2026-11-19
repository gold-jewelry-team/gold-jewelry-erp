from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.db.session import SessionLocal
from app.models.company import Company
from app.models.labor_code import LaborCodeMapping, LaborCodeSetting
from app.routers.schemas.labor_code import LaborCodeConfigRead, LaborCodeConfigUpdate

router = APIRouter(tags=["labor-code-settings"])


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


@router.get("/companies/{company_id}/labor-code-config", response_model=LaborCodeConfigRead)
def get_labor_code_config(company_id: UUID, db: Session = Depends(get_db)):
    if db.get(Company, company_id) is None:
        raise HTTPException(status_code=404, detail="找不到指定公司。")
    setting = db.get(LaborCodeSetting, company_id)
    mappings = db.scalars(select(LaborCodeMapping).where(
        LaborCodeMapping.company_id == company_id
    ).order_by(LaborCodeMapping.digit)).all()
    return LaborCodeConfigRead(
        company_id=company_id,
        prefix=setting.prefix if setting else "A",
        mappings=[{"digit": row.digit, "code_char": row.code_char} for row in mappings],
    )


@router.put("/companies/{company_id}/labor-code-config", response_model=LaborCodeConfigRead)
def update_labor_code_config(
    company_id: UUID, payload: LaborCodeConfigUpdate, db: Session = Depends(get_db)
):
    if db.get(Company, company_id) is None:
        raise HTTPException(status_code=404, detail="找不到指定公司。")
    digits = [item.digit for item in payload.mappings]
    if len(digits) != len(set(digits)):
        raise HTTPException(status_code=422, detail="暗碼數字不可重複。")

    setting = db.get(LaborCodeSetting, company_id)
    if setting is None:
        setting = LaborCodeSetting(company_id=company_id, prefix=payload.prefix.upper())
        db.add(setting)
    else:
        setting.prefix = payload.prefix.upper()

    db.execute(delete(LaborCodeMapping).where(LaborCodeMapping.company_id == company_id))
    mappings = [
        LaborCodeMapping(company_id=company_id, digit=item.digit, code_char=item.code_char)
        for item in payload.mappings
    ]
    db.add_all(mappings)
    db.commit()
    db.refresh(setting)
    return LaborCodeConfigRead(
        company_id=company_id,
        prefix=setting.prefix,
        mappings=[{"digit": row.digit, "code_char": row.code_char} for row in sorted(mappings, key=lambda row: row.digit)],
    )
