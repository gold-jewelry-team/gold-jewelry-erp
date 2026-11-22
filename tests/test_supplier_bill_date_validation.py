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
from app.models.supplier_payable import SupplierBill
from app.services.supplier_payables import create_supplier_bill


def test_supplier_bill_rejects_due_date_before_bill_date():
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    session = Session()
    try:
        company = Company(code="BILL-DATES", name="帳單日期測試銀樓")
        session.add(company)
        session.flush()
        site = Site(company_id=company.id, code="MAIN", name="總店")
        supplier = Supplier(company_id=company.id, code="SUP-01", name="測試供應商")
        session.add_all([site, supplier])
        session.commit()

        with pytest.raises(ValueError, match="到期日不可早於帳單日期"):
            create_supplier_bill(
                session,
                company_id=company.id,
                site_id=site.id,
                supplier_id=supplier.id,
                bill_no="INV-INVALID-DUE-DATE",
                bill_date=date(2026, 11, 23),
                due_date=date(2026, 11, 22),
                currency_code="TWD",
                total_amount=Decimal("250.00"),
            )

        session.rollback()
        assert session.query(SupplierBill).count() == 0
    finally:
        session.close()
        engine.dispose()
