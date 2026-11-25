import hashlib
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app import models  # noqa: F401
from app.db.base import Base
from app.main import app
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
from app.routers import google_auth


engine = create_engine(
    "sqlite+pysqlite:///:memory:",
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
TestingSessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)
client = TestClient(app)


@pytest.fixture(autouse=True)
def isolate_google_workspace_database(monkeypatch):
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    monkeypatch.setattr(google_auth, "SessionLocal", TestingSessionLocal)
    yield


def seed_google_member(status="ACTIVE", include_grants=True):
    token = "employee-workspace-session-token"
    token_hash = hashlib.sha256(token.encode("utf-8")).hexdigest()
    with TestingSessionLocal() as db:
        company = Company(code="MAIN", name="測試銀樓", is_active=True)
        user = User(
            display_name="測試店員",
            email="employee@example.com",
            is_active=True,
        )
        db.add_all([company, user])
        db.flush()

        membership = CompanyMembership(
            company_id=company.id,
            user_id=user.id,
            status=status,
            role="STAFF",
        )
        db.add(membership)
        db.flush()
        staff = CompanyRole(
            company_id=company.id,
            code="STAFF",
            name="一般成員",
            description="測試成員",
            is_system=True,
            is_active=True,
        )
        custom = CompanyRole(
            company_id=company.id,
            code="STOCK_VIEWER",
            name="庫存檢視",
            description="僅可查看商品與庫存",
            is_system=False,
            is_active=True,
        )
        db.add_all([staff, custom])
        db.flush()
        db.add_all([
            CompanyMembershipRole(membership_id=membership.id, role_id=staff.id),
            CompanyMembershipRole(membership_id=membership.id, role_id=custom.id),
        ])

        product_view = Permission(
            code="products.view",
            resource_code="products",
            action_code="view",
            name="商品－查看",
            is_active=True,
        )
        product_create = Permission(
            code="products.create",
            resource_code="products",
            action_code="create",
            name="商品－新增",
            is_active=True,
        )
        inventory_view = Permission(
            code="inventory.view",
            resource_code="inventory",
            action_code="view",
            name="庫存－查看",
            is_active=True,
        )
        db.add_all([product_view, product_create, inventory_view])
        db.flush()
        if include_grants:
            db.add_all([
                CompanyRolePermission(
                    role_id=staff.id,
                    permission_id=product_view.id,
                    is_allowed=True,
                    data_scope="OWN",
                ),
                CompanyRolePermission(
                    role_id=custom.id,
                    permission_id=product_view.id,
                    is_allowed=True,
                    data_scope="ALL",
                ),
                CompanyRolePermission(
                    role_id=custom.id,
                    permission_id=inventory_view.id,
                    is_allowed=True,
                    data_scope="OWN",
                ),
                CompanyRolePermission(
                    role_id=custom.id,
                    permission_id=product_create.id,
                    is_allowed=False,
                    data_scope="OWN",
                ),
            ])

        db.add(UserSession(
            user_id=user.id,
            token_hash=token_hash,
            expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
        ))
        db.commit()
    return token


def test_employee_page_is_only_a_public_shell_and_workspace_requires_google_session():
    page = client.get("/employee")
    assert page.status_code == 200
    assert "員工工作區" in page.text

    response = client.get("/auth/google/workspace")
    assert response.status_code == 401


def test_active_member_sees_only_own_company_and_additive_effective_permissions():
    token = seed_google_member(status="ACTIVE")

    response = client.get(
        "/auth/google/workspace",
        cookies={google_auth.settings.google_session_cookie_name: token},
    )
    assert response.status_code == 200, response.text
    assert response.headers["cache-control"] == "no-store"
    payload = response.json()
    assert payload["authenticated"] is True
    assert payload["status"] == "ACTIVE"
    assert payload["user"]["display_name"] == "測試店員"
    assert len(payload["memberships"]) == 1

    membership = payload["memberships"][0]
    assert membership["company_name"] == "測試銀樓"
    assert membership["status"] == "ACTIVE"
    assert {role["code"] for role in membership["roles"]} == {"STAFF", "STOCK_VIEWER"}

    grants = {item["code"]: item for item in membership["permissions"]}
    assert set(grants) == {"products.view", "inventory.view"}
    # Roles are additive; an ALL grant takes precedence over an OWN grant.
    assert grants["products.view"]["data_scope"] == "ALL"
    assert grants["inventory.view"]["data_scope"] == "OWN"


@pytest.mark.parametrize(
    ("membership_status", "expected_overall", "expected_grants"),
    [
        ("PENDING", "PENDING_APPROVAL", False),
        ("SUSPENDED", "SUSPENDED", False),
        ("REJECTED", "REJECTED", False),
    ],
)
def test_non_active_member_can_see_own_onboarding_status_but_no_company_grants(
    membership_status,
    expected_overall,
    expected_grants,
):
    token = seed_google_member(status=membership_status, include_grants=True)
    response = client.get(
        "/auth/google/workspace",
        cookies={google_auth.settings.google_session_cookie_name: token},
    )
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["status"] == expected_overall
    assert payload["memberships"][0]["status"] == membership_status
    assert payload["memberships"][0]["permissions"] == []
    assert expected_grants is False


def test_google_workspace_rejects_expired_or_revoked_sessions():
    token = seed_google_member()
    token_hash = hashlib.sha256(token.encode("utf-8")).hexdigest()
    with TestingSessionLocal() as db:
        session = db.scalar(select(UserSession).where(UserSession.token_hash == token_hash))
        assert session is not None
        session.revoked_at = datetime.now(timezone.utc)
        db.commit()

    response = client.get(
        "/auth/google/workspace",
        cookies={google_auth.settings.google_session_cookie_name: token},
    )
    assert response.status_code == 401
