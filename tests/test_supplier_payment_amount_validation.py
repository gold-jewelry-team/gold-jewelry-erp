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
from app.services.supplier_payables import create_supplier_bill, record_supplier_payment


def test_supplier_payment_rejects_fractional_cent_allocation():
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    session = Session()
    try:
        company = Company(code="PAY-CENTS", name="付款精度測試銀樓")
        session.add(company)
        session.flush()
        site = Site(company_id=company.id, code="MAIN", name="總店")
        supplier = Supplier(company_id=company.id, code="SUP-01", name="測試供應商")
        session.add_all([site, supplier])
        session.commit()

        bill = create_supplier_bill(
            session,
            company_id=company.id,
            site_id=site.id,
            supplier_id=supplier.id,
            bill_no="INV-CENTS",
            bill_date=date(2026, 11, 23),
            due_date=None,
            currency_code="TWD",
            total_amount=Decimal("100.00"),
        )
        session.commit()

        with pytest.raises(ValueError, match="最多只能有小數點後兩位"):
            record_supplier_payment(
                session,
                company_id=company.id,
                site_id=site.id,
                supplier_id=supplier.id,
                payment_no="SP-FRACTIONAL-CENT",
                payment_method="TRANSFER",
                allocations=[{"bill_id": bill.id, "amount": Decimal("10.001")}],
            )

        session.rollback()
        assert session.query(SupplierBill).count() == 1
        assert session.query(SupplierPayment).count() == 0
    finally:
        session.close()
        engine.dispose()
