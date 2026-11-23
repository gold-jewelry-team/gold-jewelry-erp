from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app import models  # noqa: F401
from app.db.base import Base
from app.models.company import Company
from app.models.site import Site
from app.models.supplier import Supplier
from app.models.supplier_payable import SupplierBill, SupplierPayment
from app.services.supplier_payables import (
    SupplierPaymentIdempotencyConflict,
    create_supplier_bill,
    record_supplier_payment,
)


def _payment_validation_context():
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    session = Session()
    company = Company(code="PAY-VALIDATION", name="付款驗證測試銀樓")
    session.add(company)
    session.flush()
    site = Site(company_id=company.id, code="MAIN", name="總店")
    supplier = Supplier(company_id=company.id, code="SUP-01", name="測試供應商")
    session.add_all([site, supplier])
    session.commit()
    ids = (company.id, site.id, supplier.id)
    session.close()
    return engine, Session, ids


def test_supplier_payment_rejects_unsupported_method_and_empty_allocations():
    engine, Session, (company_id, site_id, supplier_id) = _payment_validation_context()
    session = Session()
    try:
        bill = create_supplier_bill(
            session,
            company_id=company_id,
            site_id=site_id,
            supplier_id=supplier_id,
            bill_no="INV-PAY-VALIDATION",
            bill_date=date(2026, 11, 23),
            due_date=None,
            currency_code="TWD",
            total_amount=Decimal("500.00"),
        )
        session.commit()

        with pytest.raises(ValueError, match="不支援的供應商付款方式"):
            record_supplier_payment(
                session,
                company_id=company_id,
                site_id=site_id,
                supplier_id=supplier_id,
                payment_no="SP-INVALID-METHOD",
                payment_method="CHEQUE",
                allocations=[{"bill_id": bill.id, "amount": Decimal("100.00")}],
            )

        with pytest.raises(ValueError, match="至少需要一筆帳單分攤"):
            record_supplier_payment(
                session,
                company_id=company_id,
                site_id=site_id,
                supplier_id=supplier_id,
                payment_no="SP-EMPTY-ALLOCATIONS",
                payment_method="TRANSFER",
                allocations=[],
            )

        session.rollback()
        assert session.query(SupplierBill).count() == 1
        assert session.query(SupplierPayment).count() == 0
    finally:
        session.close()
        engine.dispose()

def test_duplicate_supplier_payment_number_rolls_back_without_partial_allocation():
    from app.models.supplier_payable import SupplierPaymentAllocation

    engine, Session, (company_id, site_id, supplier_id) = _payment_validation_context()
    session = Session()
    try:
        bill1 = create_supplier_bill(
            session, company_id=company_id, site_id=site_id, supplier_id=supplier_id,
            bill_no="INV-ATOMIC-001", bill_date=date(2026, 11, 23),
            due_date=None, currency_code="TWD", total_amount=Decimal("500.00"),
        )
        bill2 = create_supplier_bill(
            session, company_id=company_id, site_id=site_id, supplier_id=supplier_id,
            bill_no="INV-ATOMIC-002", bill_date=date(2026, 11, 23),
            due_date=None, currency_code="TWD", total_amount=Decimal("300.00"),
        )
        session.commit()

        record_supplier_payment(
            session, company_id=company_id, site_id=site_id, supplier_id=supplier_id,
            payment_no="SP-DUPLICATE-ATOMIC", payment_method="TRANSFER",
            allocations=[{"bill_id": bill1.id, "amount": Decimal("100.00")}],
        )
        session.commit()

        with pytest.raises(SupplierPaymentIdempotencyConflict):
            record_supplier_payment(
                session, company_id=company_id, site_id=site_id, supplier_id=supplier_id,
                payment_no="SP-DUPLICATE-ATOMIC", payment_method="CASH",
                allocations=[{"bill_id": bill2.id, "amount": Decimal("75.00")}],
            )
        session.rollback()

        assert session.query(SupplierPayment).count() == 1
        assert session.query(SupplierPaymentAllocation).count() == 1
        assert bill1.status == "PARTIALLY_PAID"
        assert bill2.status == "OPEN"
        assert bill2.paid_amount == Decimal("0")
    finally:
        session.close()
        engine.dispose()

