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
    AuthIdentity,
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


@pytest.mark.parametrize("invalid_reason", ["revoked", "expired"])
def test_google_workspace_rejects_expired_or_revoked_sessions(invalid_reason):
    token = seed_google_member()
    token_hash = hashlib.sha256(token.encode("utf-8")).hexdigest()
    with TestingSessionLocal() as db:
        session = db.scalar(select(UserSession).where(UserSession.token_hash == token_hash))
        assert session is not None
        if invalid_reason == "revoked":
            session.revoked_at = datetime.now(timezone.utc)
        else:
            session.expires_at = datetime.now(timezone.utc) - timedelta(seconds=1)
        db.commit()

    response = client.get(
        "/auth/google/workspace",
        cookies={google_auth.settings.google_session_cookie_name: token},
    )
    assert response.status_code == 401


def test_employee_workspace_lists_only_own_company_memberships_and_hides_inactive_company_grants():
    token = seed_google_member(status="ACTIVE")
    with TestingSessionLocal() as db:
        primary_user = db.scalar(select(User).where(User.email == "employee@example.com"))
        assert primary_user is not None

        second_company = Company(code="SECOND", name="第二間銀樓", is_active=True)
        inactive_company = Company(code="INACTIVE", name="停用銀樓", is_active=False)
        foreign_company = Company(code="FOREIGN", name="其他員工的公司", is_active=True)
        foreign_user = User(
            display_name="其他員工",
            email="other-employee@example.com",
            is_active=True,
        )
        db.add_all([second_company, inactive_company, foreign_company, foreign_user])
        db.flush()

        second_membership = CompanyMembership(
            company_id=second_company.id,
            user_id=primary_user.id,
            status="PENDING",
            role="STAFF",
        )
        inactive_membership = CompanyMembership(
            company_id=inactive_company.id,
            user_id=primary_user.id,
            status="ACTIVE",
            role="STAFF",
        )
        foreign_membership = CompanyMembership(
            company_id=foreign_company.id,
            user_id=foreign_user.id,
            status="ACTIVE",
            role="STAFF",
        )
        db.add_all([second_membership, inactive_membership, foreign_membership])
        db.commit()
        second_company_id = str(second_company.id)
        inactive_company_id = str(inactive_company.id)

    response = client.get(
        "/auth/google/workspace",
        cookies={google_auth.settings.google_session_cookie_name: token},
    )
    assert response.status_code == 200, response.text
    payload = response.json()
    memberships = {item["company_id"]: item for item in payload["memberships"]}

    # The signed-in user sees both of their own companies, never another user's company.
    assert len(memberships) == 3
    assert second_company_id in memberships
    assert inactive_company_id in memberships
    assert all(item["company_name"] != "其他員工的公司" for item in memberships.values())

    assert memberships[second_company_id]["status"] == "PENDING"
    assert memberships[second_company_id]["permissions"] == []
    assert memberships[inactive_company_id]["status"] == "COMPANY_INACTIVE"
    assert memberships[inactive_company_id]["permissions"] == []


@pytest.mark.parametrize("membership_status", ["SUSPENDED", "REJECTED"])
def test_rejected_or_suspended_google_user_can_sign_in_to_view_own_status(
    monkeypatch,
    membership_status,
):
    with TestingSessionLocal() as db:
        company = Company(code="STATUS", name="狀態測試銀樓", is_active=True)
        user = User(
            display_name="狀態測試成員",
            email="status-member@example.com",
            is_active=True,
        )
        db.add_all([company, user])
        db.flush()
        db.add(AuthIdentity(
            user_id=user.id,
            provider="GOOGLE",
            provider_subject="google-status-subject",
            provider_email="status-member@example.com",
            email_verified=True,
        ))
        db.add(CompanyMembership(
            company_id=company.id,
            user_id=user.id,
            status=membership_status,
            role="STAFF",
        ))
        db.commit()

    class TokenResponse:
        def raise_for_status(self):
            return None

        def json(self):
            return {"id_token": "mocked-google-id-token"}

    monkeypatch.setattr(google_auth, "_oauth_ready", lambda: None)
    monkeypatch.setattr(google_auth.requests, "post", lambda *args, **kwargs: TokenResponse())
    monkeypatch.setattr(
        google_auth.id_token,
        "verify_oauth2_token",
        lambda *_args, **_kwargs: {
            "iss": "https://accounts.google.com",
            "nonce": "expected-nonce",
            "email_verified": True,
            "sub": "google-status-subject",
            "email": "status-member@example.com",
            "name": "狀態測試成員",
        },
    )
    monkeypatch.setattr(google_auth.settings, "google_client_id", "test-google-client")
    monkeypatch.setattr(google_auth.settings, "google_client_secret", "test-google-secret")
    monkeypatch.setattr(
        google_auth.settings,
        "google_redirect_uri",
        "https://example.test/auth/google/callback",
    )
    monkeypatch.setattr(google_auth.settings, "session_cookie_secure", False)

    callback = client.get(
        "/auth/google/callback?code=mocked-code&state=expected-state",
        cookies={
            "google_oauth_state": "expected-state",
            "google_oauth_nonce": "expected-nonce",
            "google_oauth_verifier": "expected-pkce-verifier",
        },
        follow_redirects=False,
    )
    assert callback.status_code == 303, callback.text
    assert callback.headers["location"] == "/employee"

    workspace = client.get("/auth/google/workspace")
    assert workspace.status_code == 200, workspace.text
    payload = workspace.json()
    assert payload["status"] == membership_status
    assert payload["memberships"][0]["permissions"] == []
