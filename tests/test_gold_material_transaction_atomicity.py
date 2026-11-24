from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app import models  # noqa: F401
from app.db.base import Base
from app.models.company import Company
from app.models.gold_material import GoldMaterialMovement, GoldMaterialSettlementAllocation
from app.models.site import Site
from app.models.supplier import Supplier
from app.models.supplier_payable import SupplierBill
from app.services.gold_material import GoldMaterialMovementIdempotencyConflict, record_gold_material_movement
from app.services.supplier_payables import create_supplier_bill


def test_duplicate_gold_movement_number_rolls_back_bill_settlement():
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    session = Session()
    try:
        company = Company(code="GM-ATOMIC", name="金料異動原子性測試銀樓")
        session.add(company)
        session.flush()
        site = Site(company_id=company.id, code="MAIN", name="總店")
        supplier = Supplier(company_id=company.id, code="SUP-01", name="測試供應商")
        session.add_all([site, supplier])
        session.flush()

        opening = record_gold_material_movement(
            session,
            company_id=company.id,
            site_id=site.id,
            movement_no="GM-DUPLICATE-ATOMIC",
            movement_type="OPENING",
            purity_label="9999",
            purity_ratio=Decimal("1.000000"),
            gross_weight=Decimal("5.0000"),
            loss_weight=Decimal("0"),
            weight_unit_code="G",
            gold_price_value=Decimal("1000.00"),
            gold_price_unit_code="G",
            deduction_amount=Decimal("0"),
        )
        bill = create_supplier_bill(
            session,
            company_id=company.id,
            site_id=site.id,
            supplier_id=supplier.id,
            bill_no="INV-GM-ATOMIC",
            bill_date=date(2026, 11, 23),
            due_date=None,
            currency_code="TWD",
            total_amount=Decimal("1000.00"),
        )
        session.commit()

        with pytest.raises(GoldMaterialMovementIdempotencyConflict):
            record_gold_material_movement(
                session,
                company_id=company.id,
                site_id=site.id,
                supplier_id=supplier.id,
                movement_no="GM-DUPLICATE-ATOMIC",
                movement_type="SUPPLIER_DELIVERY",
                source_type="PURCHASE_SETTLEMENT",
                purity_label="9999",
                purity_ratio=Decimal("1.000000"),
                gross_weight=Decimal("1.0000"),
                loss_weight=Decimal("0"),
                weight_unit_code="G",
                gold_price_value=Decimal("1000.00"),
                gold_price_unit_code="G",
                deduction_amount=Decimal("0"),
                allocations=[{"bill_id": bill.id, "amount": Decimal("1000.00")}],
            )
        session.rollback()

        assert session.query(GoldMaterialMovement).count() == 1
        assert session.query(GoldMaterialSettlementAllocation).count() == 0
        stored_bill = session.get(SupplierBill, bill.id)
        assert stored_bill.status == "OPEN"
        assert stored_bill.paid_amount == Decimal("0")
    finally:
        session.close()
        engine.dispose()
