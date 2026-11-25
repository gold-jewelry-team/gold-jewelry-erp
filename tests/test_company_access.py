import hashlib
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app import models  # noqa: F401
from app.core.company_access import (
    authorize_google_company_request,
    company_id_from_path,
)
from app.db.base import Base
from app.models import Company, CompanyMembership, User, UserSession


engine = create_engine(
    "sqlite+pysqlite:///:memory:",
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
TestingSessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)


@pytest.fixture
def db():
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    session = TestingSessionLocal()
    try:
        yield session
    finally:
        session.close()


def seed_member(db, role="OWNER", status="ACTIVE", *, company=None, active=True, revoked=False, expired=False):
    company = company or Company(code=f"C{uuid4().hex[:8]}", name="測試公司", is_active=True)
    user = User(display_name="測試成員", email=f"{uuid4().hex}@example.com", is_active=active)
    db.add_all([company, user])
    db.flush()
    membership = CompanyMembership(
        company_id=company.id, user_id=user.id, status=status, role=role,
    )
    token = f"google-token-{uuid4().hex}"
    now = datetime.now(timezone.utc)
    db.add(UserSession(
        user_id=user.id,
        token_hash=hashlib.sha256(token.encode("utf-8")).hexdigest(),
        expires_at=now - timedelta(minutes=1) if expired else now + timedelta(hours=1),
        revoked_at=now if revoked else None,
    ))
    db.add(membership)
    db.commit()
    return company, user, membership, token


def test_company_id_is_extracted_only_from_scoped_paths():
    company_id = uuid4()
    assert company_id_from_path(f"/companies/{company_id}/products") == company_id
    assert company_id_from_path("/companies") is None
    assert company_id_from_path("/companies/not-a-uuid/products") is None
    assert company_id_from_path("/admin/api/members") is None


@pytest.mark.parametrize("method", ["GET", "POST", "PUT", "PATCH", "DELETE"])
def test_owner_role_can_access_all_company_api_methods(db, method):
    company, _user, _membership, token = seed_member(db, role="OWNER")
    grant = authorize_google_company_request(db, token, company.id, method)
    assert grant["company_id"] == company.id
    assert grant["role"] == "OWNER"


def test_manager_role_is_read_only(db):
    company, _user, _membership, token = seed_member(db, role="MANAGER")
    grant = authorize_google_company_request(db, token, company.id, "GET")
    assert grant["role"] == "MANAGER"

    with pytest.raises(HTTPException) as exc:
        authorize_google_company_request(db, token, company.id, "POST")
    assert exc.value.status_code == 403


def test_staff_role_fails_closed_until_own_record_scope_is_available(db):
    company, _user, _membership, token = seed_member(db, role="STAFF")
    with pytest.raises(HTTPException) as exc:
        authorize_google_company_request(db, token, company.id, "GET")
    assert exc.value.status_code == 403
    assert "僅本人資料範圍尚未完成" in exc.value.detail


def test_pending_membership_cannot_access_company_data(db):
    company, _user, _membership, token = seed_member(db, role="OWNER", status="PENDING")
    with pytest.raises(HTTPException) as exc:
        authorize_google_company_request(db, token, company.id, "GET")
    assert exc.value.status_code == 403


def test_membership_for_another_company_cannot_be_reused(db):
    allowed_company, _user, _membership, token = seed_member(db, role="OWNER")
    other_company = Company(code=f"X{uuid4().hex[:8]}", name="另一間公司", is_active=True)
    db.add(other_company)
    db.commit()

    assert authorize_google_company_request(
        db, token, allowed_company.id, "GET"
    )["company_id"] == allowed_company.id
    with pytest.raises(HTTPException) as exc:
        authorize_google_company_request(db, token, other_company.id, "GET")
    assert exc.value.status_code == 403


@pytest.mark.parametrize(
    "kwargs,expected_status",
    [
        ({"active": False}, 403),
        ({"revoked": True}, 401),
        ({"expired": True}, 401),
    ],
)
def test_inactive_user_revoked_or_expired_session_is_rejected(db, kwargs, expected_status):
    company, _user, _membership, token = seed_member(db, role="OWNER", **kwargs)
    with pytest.raises(HTTPException) as exc:
        authorize_google_company_request(db, token, company.id, "GET")
    assert exc.value.status_code == expected_status


def test_membership_cannot_access_inactive_company(db):
    company, _user, _membership, token = seed_member(db, role="OWNER")
    company.is_active = False
    db.commit()

    with pytest.raises(HTTPException) as exc:
        authorize_google_company_request(db, token, company.id, "GET")
    assert exc.value.status_code == 404
