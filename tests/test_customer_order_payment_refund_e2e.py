from decimal import Decimal
from uuid import UUID, uuid4

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app import models  # noqa: F401
from app.db.base import Base
from app.main import app
from app.models.company import Company
from app.models.customer_order import CustomerOrder
from app.models.payment_transaction import PaymentTransaction
from app.models.site import Site
from app.routers import customer_orders


def _setup():
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    with Session() as db:
        company = Company(code="ORDER-COLLECT-REFUND", name="客訂收退款流程測試")
        db.add(company)
        db.flush()
        site = Site(company_id=company.id, code="MAIN", name="總店")
        db.add(site)
        db.commit()
        company_id, site_id = company.id, site.id

    def override_db():
        session = Session()
        try:
            yield session
        finally:
            session.close()

    app.dependency_overrides.clear()
    app.dependency_overrides[customer_orders.get_db] = override_db
    return engine, Session, company_id, site_id


def test_customer_order_extra_collection_partial_refund_and_tail_payment_are_idempotent():
    engine, Session, company_id, site_id = _setup()
    try:
        client = TestClient(app)
        create_key = str(uuid4())
        created = client.post(f"/companies/{company_id}/customer-orders", json={
            "site_id": str(site_id),
            "order_no": "CO-RECEIPT-001",
            "customer_name": "客訂收退款測試",
            "items": [{"product_name": "黃金項鍊", "weight": 2.0}],
            "total_amount": "10000.00",
            "initial_deposit": "2000.00",
            "payment_method": "CASH",
            "idempotency_key": create_key,
        })
        assert created.status_code == 201, created.text
        order_id = created.json()["id"]

        collect_key = str(uuid4())
        collect_payload = {
            "amount": "3000.00",
            "payment_method": "TRANSFER",
            "note": "追加訂金",
            "idempotency_key": collect_key,
        }
        payment_url = f"/companies/{company_id}/customer-orders/{order_id}/payments"
        first_collection = client.post(payment_url, json=collect_payload)
        replay_collection = client.post(payment_url, json=collect_payload)
        assert first_collection.status_code == 200, first_collection.text
        assert replay_collection.status_code == 200, replay_collection.text
        assert replay_collection.json()["deposit_amount"] == "5000.00"
        assert len(replay_collection.json()["payments"]) == 2

        refund_key = str(uuid4())
        refund_payload = {
            "amount": "1000.00",
            "payment_method": "CASH",
            "note": "部分退還訂金",
            "idempotency_key": refund_key,
        }
        refund_url = f"/companies/{company_id}/customer-orders/{order_id}/refunds"
        first_refund = client.post(refund_url, json=refund_payload)
        replay_refund = client.post(refund_url, json=refund_payload)
        assert first_refund.status_code == 200, first_refund.text
        assert replay_refund.status_code == 200, replay_refund.text
        assert replay_refund.json()["deposit_amount"] == "4000.00"
        assert replay_refund.json()["balance_amount"] == "6000.00"
        assert len(replay_refund.json()["payments"]) == 3

        tail_key = str(uuid4())
        tail_payload = {
            "amount": "6000.00",
            "payment_method": "TRANSFER",
            "note": "交貨尾款",
            "idempotency_key": tail_key,
        }
        tail = client.post(payment_url, json=tail_payload)
        assert tail.status_code == 200, tail.text
        assert tail.json()["deposit_amount"] == "10000.00"
        assert tail.json()["balance_amount"] == "0.00"
        assert len(tail.json()["payments"]) == 4

        for next_status in ("ARRIVED", "READY"):
            changed = client.patch(
                f"/companies/{company_id}/customer-orders/{order_id}/status",
                params={"status": next_status},
            )
            assert changed.status_code == 200, changed.text
            assert changed.json()["status"] == next_status

        direct_completion = client.patch(
            f"/companies/{company_id}/customer-orders/{order_id}/status",
            params={"status": "COMPLETED"},
        )
        assert direct_completion.status_code == 409
        assert "必須透過正式銷售單完成" in direct_completion.json()["detail"]

        # A response-lost refund retry remains an exact replay without completing fulfillment.
        final_refund_replay = client.post(refund_url, json=refund_payload)
        assert final_refund_replay.status_code == 200, final_refund_replay.text
        assert final_refund_replay.json()["status"] == "READY"
        assert final_refund_replay.json()["deposit_amount"] == "10000.00"
        assert len(final_refund_replay.json()["payments"]) == 4

        with Session() as db:
            order = db.get(CustomerOrder, UUID(order_id))
            payments = list(db.scalars(select(PaymentTransaction).where(
                PaymentTransaction.customer_order_id == UUID(order_id)
            ).order_by(PaymentTransaction.paid_at, PaymentTransaction.id)).all())
            assert order.status == "READY"
            assert order.deposit_amount == Decimal("10000.00")
            assert len(payments) == 4
            assert [item.direction for item in payments] == ["IN", "IN", "OUT", "IN"]
            assert sum(
                (item.amount if item.direction == "IN" else -item.amount for item in payments),
                Decimal("0"),
            ) == Decimal("10000.00")
    finally:
        app.dependency_overrides.clear()
        Base.metadata.drop_all(engine)
        engine.dispose()
