import hashlib
from datetime import datetime, timedelta, timezone
from uuid import UUID

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app import models  # noqa: F401
from app.db.base import Base
from app.main import app
from app.models import AuthIdentity, Company, CompanyMembership, User, UserSession
from app.routers.member_admin import get_db

engine = create_engine(
    "sqlite+pysqlite:///:memory:",
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
TestingSessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)
client = TestClient(app)


def override_get_db():
    db = TestingSessionLocal()
    try:
        yield db
    finally:
        db.close()


@pytest.fixture(autouse=True)
def isolate_member_admin_database():
    app.dependency_overrides[get_db] = override_get_db
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    try:
        yield
    finally:
        app.dependency_overrides.pop(get_db, None)


def seed_user_and_company():
    with TestingSessionLocal() as db:
        company = Company(code="MAIN", name="測試銀樓", is_active=True)
        user = User(display_name="測試成員", email="member@example.com", is_active=True)
        db.add_all([company, user])
        db.flush()
        db.add(AuthIdentity(
            user_id=user.id, provider="GOOGLE",
            provider_subject="google-sub-123",
            provider_email="member@example.com", email_verified=True,
        ))
        db.commit()
        return str(user.id), str(company.id)


def test_admin_can_assign_approve_suspend_and_reactivate_member():
    user_id, company_id = seed_user_and_company()

    assigned = client.post(
        f"/admin/api/users/{user_id}/memberships",
        json={"company_id": company_id, "role": "STAFF"},
    )
    assert assigned.status_code == 201, assigned.text
    membership_id = assigned.json()["id"]
    assert assigned.json()["status"] == "PENDING"

    pending_list = client.get("/admin/api/members")
    assert pending_list.status_code == 200
    member = next(item for item in pending_list.json() if item["id"] == user_id)
    assert member["memberships"][0]["status"] == "PENDING"

    approved = client.patch(
        f"/admin/api/memberships/{membership_id}",
        json={"action": "APPROVE", "role": "MANAGER"},
    )
    assert approved.status_code == 200, approved.text
    assert approved.json()["status"] == "ACTIVE"
    assert approved.json()["role"] == "MANAGER"

    suspended = client.patch(
        f"/admin/api/memberships/{membership_id}",
        json={"action": "SUSPEND"},
    )
    assert suspended.status_code == 200, suspended.text
    assert suspended.json()["status"] == "SUSPENDED"

    reactivated = client.patch(
        f"/admin/api/memberships/{membership_id}",
        json={"action": "REACTIVATE"},
    )
    assert reactivated.status_code == 200, reactivated.text
    assert reactivated.json()["status"] == "ACTIVE"


def test_suspending_last_membership_revokes_google_sessions():
    user_id, company_id = seed_user_and_company()
    token_hash = hashlib.sha256(b"test-session-token").hexdigest()
    with TestingSessionLocal() as db:
        membership = CompanyMembership(
            user_id=UUID(user_id), company_id=UUID(company_id), status="ACTIVE", role="STAFF"
        )
        session = UserSession(
            user_id=__import__('uuid').UUID(user_id), token_hash=token_hash,
            expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
        )
        db.add_all([membership, session])
        db.commit()
        membership_id = str(membership.id)

    response = client.patch(
        f"/admin/api/memberships/{membership_id}",
        json={"action": "SUSPEND"},
    )
    assert response.status_code == 200, response.text

    with TestingSessionLocal() as db:
        stored = db.scalar(select(UserSession).where(UserSession.token_hash == token_hash))
        assert stored is not None
        assert stored.revoked_at is not None


def test_admin_can_assign_company_to_user_without_existing_membership():
    user_id, company_id = seed_user_and_company()
    response = client.get("/admin/api/companies")
    assert response.status_code == 200
    assert response.json() == [{"id": company_id, "name": "測試銀樓", "code": "MAIN"}]

    assigned = client.post(
        f"/admin/api/users/{user_id}/memberships",
        json={"company_id": company_id, "role": "STAFF"},
    )
    assert assigned.status_code == 201
    assert assigned.json()["status"] == "PENDING"


def test_inactive_user_cannot_be_assigned_and_existing_sessions_are_revoked():
    user_id, company_id = seed_user_and_company()
    token_hash = hashlib.sha256(b"another-session-token").hexdigest()
    with TestingSessionLocal() as db:
        db.add(UserSession(
            user_id=UUID(user_id), token_hash=token_hash,
            expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
        ))
        db.commit()

    response = client.patch(
        f"/admin/api/users/{user_id}",
        json={"is_active": False},
    )
    assert response.status_code == 200
    assert response.json()["is_active"] is False

    assigned = client.post(
        f"/admin/api/users/{user_id}/memberships",
        json={"company_id": company_id, "role": "STAFF"},
    )
    assert assigned.status_code == 409

    with TestingSessionLocal() as db:
        stored = db.scalar(select(UserSession).where(UserSession.token_hash == token_hash))
        assert stored is not None
        assert stored.revoked_at is not None


def test_membership_transition_rejects_invalid_state():
    user_id, company_id = seed_user_and_company()
    with TestingSessionLocal() as db:
        membership = CompanyMembership(
            user_id=UUID(user_id), company_id=UUID(company_id), status="ACTIVE", role="STAFF"
        )
        db.add(membership)
        db.commit()
        membership_id = str(membership.id)

    response = client.patch(
        f"/admin/api/memberships/{membership_id}",
        json={"action": "APPROVE"},
    )
    assert response.status_code == 409
