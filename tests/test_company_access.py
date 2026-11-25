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


def _build_request(path, method, cookie_name, cookie_value):
    from starlette.requests import Request

    scope = {
        "type": "http",
        "asgi": {"version": "3.0"},
        "http_version": "1.1",
        "method": method,
        "scheme": "https",
        "path": path,
        "raw_path": path.encode("ascii"),
        "query_string": b"",
        "headers": [
            (b"host", b"testserver"),
            (b"cookie", f"{cookie_name}={cookie_value}".encode("ascii")),
        ],
        "client": ("127.0.0.1", 12345),
        "server": ("testserver", 443),
        "root_path": "",
    }
    return Request(scope)


def _configure_production_auth(monkeypatch):
    from app.core.config import settings

    monkeypatch.setattr(settings, "environment", "production")
    monkeypatch.setattr(settings, "admin_username", "owner")
    monkeypatch.setattr(settings, "admin_password", "test-password-12345")
    monkeypatch.setattr(settings, "session_secret_key", "test-session-secret-key-at-least-32-chars")
    monkeypatch.setattr(settings, "session_cookie_name", "test_admin_session")
    monkeypatch.setattr(settings, "google_session_cookie_name", "test_google_session")


def test_security_middleware_enforces_exact_company_membership(db, monkeypatch):
    import asyncio
    import json

    import app.main as main_module
    from starlette.responses import JSONResponse

    company, _user, _membership, token = seed_member(db, role="OWNER")
    other_company = Company(code=f"Z{uuid4().hex[:8]}", name="未授權公司", is_active=True)
    db.add(other_company)
    db.commit()
    _configure_production_auth(monkeypatch)
    monkeypatch.setattr(main_module, "SessionLocal", TestingSessionLocal)

    async def downstream(request):
        return JSONResponse({"role": request.state.company_role})

    allowed_request = _build_request(
        f"/companies/{company.id}/products", "GET", "test_google_session", token
    )
    allowed = asyncio.run(main_module.security_middleware(allowed_request, downstream))
    assert allowed.status_code == 200
    assert json.loads(allowed.body)["role"] == "OWNER"

    denied_request = _build_request(
        f"/companies/{other_company.id}/products", "GET", "test_google_session", token
    )
    denied = asyncio.run(main_module.security_middleware(denied_request, downstream))
    assert denied.status_code == 403


def test_security_middleware_preserves_owner_admin_session(db, monkeypatch):
    import asyncio
    import json

    import app.main as main_module
    from app.core.auth import create_session_token
    from starlette.responses import JSONResponse

    company = Company(code=f"A{uuid4().hex[:8]}", name="店家", is_active=True)
    db.add(company)
    db.commit()
    _configure_production_auth(monkeypatch)
    monkeypatch.setattr(main_module, "SessionLocal", TestingSessionLocal)

    async def downstream(request):
        return JSONResponse({"admin": request.state.admin_username})

    request = _build_request(
        f"/companies/{company.id}/products",
        "GET",
        "test_admin_session",
        create_session_token("owner"),
    )
    response = asyncio.run(main_module.security_middleware(request, downstream))
    assert response.status_code == 200
    assert json.loads(response.body)["admin"] == "owner"
