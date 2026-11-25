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
from app.core.auth import create_session_token
from app.core.config import settings
from app.main import app
from app.models import (AuthIdentity, Company, CompanyMembership, CompanyMembershipRole, CompanyRole, CompanyRolePermission, Permission, User, UserSession)
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
            user_id=UUID(user_id), token_hash=token_hash,
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



def test_member_management_requires_administrator_session(monkeypatch):
    monkeypatch.setattr(settings, "environment", "production")
    monkeypatch.setattr(settings, "admin_username", "owner")
    monkeypatch.setattr(settings, "admin_password", "test-password-12345")
    monkeypatch.setattr(settings, "session_secret_key", "test-session-secret-key-at-least-32-chars")
    monkeypatch.setattr(settings, "session_cookie_secure", False)
    monkeypatch.setattr(settings, "session_max_age_seconds", 3600)

    google_only = client.get(
        "/admin/api/members",
        cookies={settings.google_session_cookie_name: "google-session-only"},
    )
    assert google_only.status_code == 401

    no_session = client.get("/member-management")
    assert no_session.status_code == 401
    no_role_session = client.get("/role-management")
    assert no_role_session.status_code == 401

    admin_token = create_session_token("owner")
    admin_page = client.get(
        "/member-management",
        cookies={settings.session_cookie_name: admin_token},
    )
    assert admin_page.status_code == 200
    assert "家庭／店員成員管理" in admin_page.text

    role_page = client.get(
        "/role-management",
        cookies={settings.session_cookie_name: admin_token},
    )
    assert role_page.status_code == 200
    assert "角色與權限管理" in role_page.text


def seed_permission_catalog(company_id):
    with TestingSessionLocal() as db:
        for resource, resource_name in (
            ("products", "商品"),
            ("inventory", "庫存"),
        ):
            for action, action_name in (
                ("view", "查看"), ("create", "新增"),
                ("update", "修改"), ("void", "作廢"),
            ):
                db.add(Permission(
                    code=f"{resource}.{action}",
                    resource_code=resource,
                    action_code=action,
                    name=f"{resource_name}-{action_name}",
                    is_active=True,
                ))
        db.commit()


def test_owner_can_create_custom_role_and_configure_permissions():
    user_id, company_id = seed_user_and_company()
    seed_permission_catalog(company_id)

    roles_response = client.get(f"/admin/api/companies/{company_id}/roles")
    assert roles_response.status_code == 200, roles_response.text
    system_roles = {row["code"]: row for row in roles_response.json()}
    assert {"OWNER", "MANAGER", "STAFF"} <= set(system_roles)

    created = client.post(
        f"/admin/api/companies/{company_id}/roles",
        json={"code": "STOCK_VIEWER", "name": "庫存檢視", "description": "僅查看商品與庫存"},
    )
    assert created.status_code == 201, created.text
    role = created.json()
    assert role["is_system"] is False
    assert all(not item["is_allowed"] for item in role["permissions"])

    updated = client.put(
        f"/admin/api/roles/{role['id']}/permissions",
        json={"permissions": [
            {"code": "products.view", "is_allowed": True, "data_scope": "ALL"},
            {"code": "inventory.view", "is_allowed": True, "data_scope": "OWN"},
            {"code": "products.create", "is_allowed": False, "data_scope": "OWN"},
        ]},
    )
    assert updated.status_code == 200, updated.text
    grants = {item["code"]: item for item in updated.json()["permissions"]}
    assert grants["products.view"]["is_allowed"] is True
    assert grants["products.view"]["data_scope"] == "ALL"
    assert grants["inventory.view"]["data_scope"] == "OWN"
    assert grants["products.create"]["is_allowed"] is False


def test_membership_can_hold_multiple_company_roles_but_not_foreign_company_roles():
    user_id, company_id = seed_user_and_company()
    seed_permission_catalog(company_id)
    client.get(f"/admin/api/companies/{company_id}/roles")

    with TestingSessionLocal() as db:
        membership = CompanyMembership(
            user_id=UUID(user_id), company_id=UUID(company_id),
            status="PENDING", role="STAFF",
        )
        other_company = Company(code="OTHER", name="另一間公司", is_active=True)
        db.add_all([membership, other_company])
        db.flush()
        role_a = db.scalar(select(CompanyRole).where(
            CompanyRole.company_id == UUID(company_id), CompanyRole.code == "STAFF"
        ))
        role_b = CompanyRole(
            company_id=UUID(company_id), code="STOCK_VIEWER", name="庫存檢視",
            is_system=False, is_active=True,
        )
        foreign_role = CompanyRole(
            company_id=other_company.id, code="FOREIGN", name="其他公司角色",
            is_system=False, is_active=True,
        )
        db.add_all([role_b, foreign_role])
        db.commit()
        membership_id = str(membership.id)
        role_ids = [str(role_a.id), str(role_b.id)]
        foreign_role_id = str(foreign_role.id)

    assigned = client.put(
        f"/admin/api/memberships/{membership_id}/roles",
        json={"role_ids": role_ids},
    )
    assert assigned.status_code == 200, assigned.text
    assert set(assigned.json()["role_ids"]) == set(role_ids)

    rejected = client.put(
        f"/admin/api/memberships/{membership_id}/roles",
        json={"role_ids": [foreign_role_id]},
    )
    assert rejected.status_code == 422


def test_member_list_returns_503_until_role_schema_is_migrated():
    Base.metadata.drop_all(
        engine,
        tables=[
            CompanyRolePermission.__table__,
            CompanyMembershipRole.__table__,
            CompanyRole.__table__,
            Permission.__table__,
        ],
    )
    response = client.get("/admin/api/members")
    assert response.status_code == 503
    assert "Migration" in response.json()["detail"]
