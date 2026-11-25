from uuid import uuid4

from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app import models  # noqa: F401
from app.core.actor_context import ActorContext, current_actor
from app.db.base import Base
from app.models import Company, RecordActor, Supplier, User


engine = create_engine(
    "sqlite+pysqlite:///:memory:",
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
TestingSessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)


def setup_database():
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)


def save_supplier(company_id, code, user_id):
    token = current_actor.set(ActorContext(
        actor_type="GOOGLE", user_id=user_id, company_id=company_id,
        data_scope="ALL", permission_code="suppliers.create",
    ))
    try:
        with TestingSessionLocal() as db:
            supplier = Supplier(
                company_id=company_id,
                code=code,
                name=f"供應商 {code}",
                is_active=True,
            )
            db.add(supplier)
            db.commit()
            return supplier.id
    finally:
        current_actor.reset(token)


def test_new_business_record_tracks_google_creator_and_last_modifier():
    setup_database()
    with TestingSessionLocal() as db:
        company = Company(code=f"C{uuid4().hex[:8]}", name="測試銀樓", is_active=True)
        user = User(display_name="店員", email="staff@example.com", is_active=True)
        db.add_all([company, user])
        db.commit()
        company_id, user_id = company.id, user.id

    supplier_id = save_supplier(company_id, "S001", user_id)
    with TestingSessionLocal() as db:
        record = db.scalar(select(RecordActor).where(
            RecordActor.resource_code == "suppliers",
            RecordActor.record_id == supplier_id,
        ))
        assert record is not None
        assert record.created_by_user_id == user_id
        assert record.updated_by_user_id == user_id
        assert record.created_by_admin_username is None

    token = current_actor.set(ActorContext(
        actor_type="ADMIN", admin_username="owner",
    ))
    try:
        with TestingSessionLocal() as db:
            supplier = db.get(Supplier, supplier_id)
            supplier.name = "供應商更新"
            db.commit()
    finally:
        current_actor.reset(token)

    with TestingSessionLocal() as db:
        record = db.scalar(select(RecordActor).where(
            RecordActor.resource_code == "suppliers",
            RecordActor.record_id == supplier_id,
        ))
        assert record.created_by_user_id == user_id
        assert record.updated_by_user_id is None
        assert record.updated_by_admin_username == "owner"


def test_own_scope_filters_orm_reads_to_the_authenticated_creator():
    setup_database()
    with TestingSessionLocal() as db:
        company = Company(code=f"C{uuid4().hex[:8]}", name="測試銀樓", is_active=True)
        user_a = User(display_name="店員A", email="a@example.com", is_active=True)
        user_b = User(display_name="店員B", email="b@example.com", is_active=True)
        db.add_all([company, user_a, user_b])
        db.commit()
        company_id, user_a_id, user_b_id = company.id, user_a.id, user_b.id

    save_supplier(company_id, "S-A", user_a_id)
    save_supplier(company_id, "S-B", user_b_id)

    token = current_actor.set(ActorContext(
        actor_type="GOOGLE",
        user_id=user_a_id,
        company_id=company_id,
        data_scope="OWN",
        permission_code="suppliers.view",
    ))
    try:
        with TestingSessionLocal() as db:
            visible = list(db.scalars(
                select(Supplier).where(Supplier.company_id == company_id)
            ).all())
            assert [item.code for item in visible] == ["S-A"]
    finally:
        current_actor.reset(token)

    token = current_actor.set(ActorContext(
        actor_type="GOOGLE",
        user_id=user_a_id,
        company_id=company_id,
        data_scope="ALL",
        permission_code="suppliers.view",
    ))
    try:
        with TestingSessionLocal() as db:
            visible = list(db.scalars(
                select(Supplier).where(Supplier.company_id == company_id)
            ).all())
            assert {item.code for item in visible} == {"S-A", "S-B"}
    finally:
        current_actor.reset(token)


def test_historical_record_without_actor_is_not_visible_to_own_scope():
    setup_database()
    with TestingSessionLocal() as db:
        company = Company(code=f"C{uuid4().hex[:8]}", name="測試銀樓", is_active=True)
        user = User(display_name="店員", email="staff@example.com", is_active=True)
        db.add_all([company, user])
        db.flush()
        db.add(Supplier(company_id=company.id, code="OLD", name="歷史資料", is_active=True))
        db.commit()
        company_id, user_id = company.id, user.id

    token = current_actor.set(ActorContext(
        actor_type="GOOGLE",
        user_id=user_id,
        company_id=company_id,
        data_scope="OWN",
        permission_code="suppliers.view",
    ))
    try:
        with TestingSessionLocal() as db:
            visible = list(db.scalars(select(Supplier).where(
                Supplier.company_id == company_id
            )).all())
            assert visible == []
    finally:
        current_actor.reset(token)
