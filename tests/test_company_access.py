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
    permission_for_request,
)
from app.db.base import Base
from app.models import (
    Company,
    CompanyMembership,
    CompanyMembershipRole,
    CompanyRole,
    CompanyRolePermission,
    Permission,
    User,
    UserSession,
)


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
    db.add(membership)
    db.flush()
    company_role = CompanyRole(
        company_id=company.id, code=role, name=role, is_system=True, is_active=True,
    )
    db.add(company_role)
    db.flush()
    membership_role = CompanyMembershipRole(
        membership_id=membership.id, role_id=company_role.id,
    )
    token = f"google-token-{uuid4().hex}"
    now = datetime.now(timezone.utc)
    db.add(UserSession(
        user_id=user.id,
        token_hash=hashlib.sha256(token.encode("utf-8")).hexdigest(),
        expires_at=now - timedelta(minutes=1) if expired else now + timedelta(hours=1),
        revoked_at=now if revoked else None,
    ))
    db.add(membership_role)
    actions = ("view", "create", "update", "void")
    for action in actions:
        permission = Permission(
            code=f"products.{action}",
            resource_code="products",
            action_code=action,
            name=f"商品-{action}",
            is_active=True,
        )
        db.add(permission)
        db.flush()
        allowed = role == "OWNER" or (role == "MANAGER" and action == "view")
        db.add(CompanyRolePermission(
            role_id=company_role.id,
            permission_id=permission.id,
            is_allowed=allowed,
            data_scope="ALL" if role != "STAFF" else "OWN",
        ))
    db.commit()
    return company, user, membership, token


def test_company_id_is_extracted_only_from_scoped_paths():
    company_id = uuid4()
    assert company_id_from_path(f"/companies/{company_id}/products") == company_id
    assert company_id_from_path("/companies") is None
    assert company_id_from_path("/companies/not-a-uuid/products") is None
    assert company_id_from_path("/admin/api/members") is None


@pytest.mark.parametrize(
    "path,method,expected",
    [
        ("/companies/00000000-0000-0000-0000-000000000001/products", "GET", "products.view"),
        ("/companies/00000000-0000-0000-0000-000000000001/products", "POST", "products.create"),
        ("/companies/00000000-0000-0000-0000-000000000001/products/00000000-0000-0000-0000-000000000002", "PATCH", "products.update"),
        ("/companies/00000000-0000-0000-0000-000000000001/sales/00000000-0000-0000-0000-000000000002/void", "POST", "sales.void"),
        ("/companies/00000000-0000-0000-0000-000000000001/sales/returns/00000000-0000-0000-0000-000000000002/payments", "POST", "payments.create"),
        ("/companies/00000000-0000-0000-0000-000000000001/customer-orders/00000000-0000-0000-0000-000000000002/refunds", "POST", "payments.create"),
        ("/companies/00000000-0000-0000-0000-000000000001/operating-expenses/00000000-0000-0000-0000-000000000002/pay", "POST", "expenses.update"),
        ("/companies/00000000-0000-0000-0000-000000000001/supplier-payables/bills/00000000-0000-0000-0000-000000000002/void", "POST", "supplier_payables.void"),
        ("/companies/00000000-0000-0000-0000-000000000001/bank-accounts/00000000-0000-0000-0000-000000000002/statement-imports", "GET", "bank_reconciliation.view"),
        ("/companies/00000000-0000-0000-0000-000000000001/suppliers/00000000-0000-0000-0000-000000000002/category-offerings", "POST", "supplier_offerings.create"),
        ("/companies/00000000-0000-0000-0000-000000000001/products/00000000-0000-0000-0000-000000000002/supplier-offerings", "GET", "supplier_offerings.view"),
    ],
)
def test_permission_code_maps_route_and_action(path, method, expected):
    assert permission_for_request(path, method) == expected


def test_unmapped_company_api_fails_closed():
    with pytest.raises(HTTPException) as exc:
        permission_for_request("/companies/00000000-0000-0000-0000-000000000001/unmapped", "GET")
    assert exc.value.status_code == 403


@pytest.mark.parametrize("method", ["GET", "POST", "PUT", "PATCH", "DELETE"])
def test_owner_role_can_access_all_company_products_methods(db, method):
    company, _user, _membership, token = seed_member(db, role="OWNER")
    grant = authorize_google_company_request(db, token, company.id, method)
    assert grant["company_id"] == company.id
    assert grant["role"] == "OWNER"
    assert grant["data_scope"] == "ALL"


def test_manager_role_is_read_only_from_permission_catalog(db):
    company, _user, _membership, token = seed_member(db, role="MANAGER")
    grant = authorize_google_company_request(db, token, company.id, "GET")
    assert grant["role"] == "MANAGER"
    with pytest.raises(HTTPException) as exc:
        authorize_google_company_request(db, token, company.id, "POST")
    assert exc.value.status_code == 403


def test_staff_role_has_no_access_until_owner_grants_permissions(db):
    company, _user, _membership, token = seed_member(db, role="STAFF")
    with pytest.raises(HTTPException) as exc:
        authorize_google_company_request(db, token, company.id, "GET")
    assert exc.value.status_code == 403
    assert "未獲授權" in exc.value.detail


def test_custom_role_permission_is_used_instead_of_legacy_role_label(db):
    company, _user, membership, token = seed_member(db, role="STAFF")
    custom = CompanyRole(
        company_id=company.id, code="STOCK_VIEWER", name="庫存檢視", is_system=False,
    )
    db.add(custom)
    db.flush()
    permission = db.scalar(
        __import__("sqlalchemy").select(Permission).where(Permission.code == "products.view")
    )
    db.add_all([
        CompanyMembershipRole(membership_id=membership.id, role_id=custom.id),
        CompanyRolePermission(
            role_id=custom.id, permission_id=permission.id,
            is_allowed=True, data_scope="ALL",
        ),
    ])
    db.commit()
    grant = authorize_google_company_request(db, token, company.id, "GET")
    assert grant["permission_code"] == "products.view"
    assert grant["data_scope"] == "ALL"


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


def test_every_company_scoped_api_route_has_a_permission_mapping():
    from app.main import app

    unmapped = []
    checked = 0
    http_methods = {"get": "GET", "post": "POST", "put": "PUT", "patch": "PATCH", "delete": "DELETE"}
    for route_path, path_item in app.openapi()["paths"].items():
        if not route_path.startswith("/companies/{company_id}/"):
            continue
        for method_name, method in path_item.items():
            if method_name.lower() not in http_methods:
                continue
            verb = http_methods[method_name.lower()]
            try:
                permission_for_request(route_path, verb)
                checked += 1
            except HTTPException as exc:
                unmapped.append(f"{verb} {route_path}: {exc.detail}")

    assert checked > 0, "No company-scoped API routes were discovered in OpenAPI."
    assert not unmapped, "Company routes missing explicit permission mappings:\\n" + "\\n".join(unmapped)


def test_company_management_root_routes_are_not_granted_to_google_members():
    # Creating a company or changing company-wide identity/settings is an
    # administrator operation, not a member operation on an existing company.
    for method in ("GET", "POST", "PATCH", "DELETE"):
        with pytest.raises(HTTPException) as exc:
            permission_for_request("/companies/{company_id}", method)
        assert exc.value.status_code == 403
