import hashlib
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app import models  # noqa: F401
from app.core.actor_context import ActorContext, current_actor
from app.core.company_access import (
    additional_permissions_for_request,
    authorize_google_company_request,
    company_id_from_path,
    permission_for_request,
    require_current_actor_permission,
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
        ("/companies/{company_id}/sales", "GET", ["payments.view"]),
        ("/companies/{company_id}/sales", "POST", ["gold_prices.view", "payments.create"]),
        ("/companies/{company_id}/sales/{sale_id}", "PATCH", ["gold_prices.view", "payments.update"]),
        ("/companies/{company_id}/sales/{sale_id}/complete", "POST", ["inventory.create"]),
        ("/companies/{company_id}/purchases", "POST", ["products.view", "suppliers.view"]),
        ("/companies/{company_id}/purchases/{purchase_id}", "PATCH", ["products.view", "suppliers.view"]),
        ("/companies/{company_id}/purchases/{purchase_id}/receive", "POST", ["inventory.create"]),
        ("/companies/{company_id}/sales/{sale_id}/returns", "POST", ["inventory.create", "sales.view"]),
        ("/companies/{company_id}/sales/{sale_id}/returns", "GET", ["sales.view"]),
        ("/companies/{company_id}/sales/{sale_id}/returns/{return_id}", "GET", ["sales.view"]),
        ("/companies/{company_id}/sales/{sale_id}/payments", "POST", ["sales.view"]),
        ("/companies/{company_id}/sales/returns/{return_id}/payments", "POST", ["sales_returns.view"]),
        ("/companies/{company_id}/customer-orders", "POST", ["payments.create", "payments.view"]),
        ("/companies/{company_id}/customer-orders", "GET", ["payments.view"]),
        ("/companies/{company_id}/customer-orders/{order_id}/payments", "POST", ["customer_orders.update", "payments.view"]),
        ("/companies/{company_id}/customer-orders/{order_id}/refunds", "POST", ["customer_orders.update", "payments.view"]),
        ("/companies/{company_id}/operating-expenses/{expense_id}/pay", "POST", ["payments.create"]),
        ("/companies/{company_id}/bank-accounts/{account_id}/statement-imports", "GET", ["bank_accounts.view"]),
        ("/companies/{company_id}/bank-accounts/{account_id}/statement-imports/{import_id}/lines/{line_id}/adjustment", "POST", ["bank_accounts.create", "bank_accounts.view"]),
        ("/companies/{company_id}/bank-accounts/{account_id}/reconciliation-report", "GET", ["bank_accounts.view"]),
        ("/companies/{company_id}/bank-accounts/{account_id}/cash-deposits", "POST", ["cash_drawer.create"]),
        ("/companies/{company_id}/bank-accounts/{account_id}/cash-withdrawals", "POST", ["cash_drawer.create"]),
        ("/companies/{company_id}/gold-material/movements", "GET", ["supplier_payables.view"]),
                ("/companies/{company_id}/supplier-category-offerings", "GET", ["product_categories.view", "suppliers.view"]),
        ("/companies/{company_id}/suppliers/{supplier_id}/category-offerings", "POST", ["product_categories.view", "suppliers.view"]),
        ("/companies/{company_id}/supplier-product-offerings", "GET", ["products.view", "suppliers.view"]),
        ("/companies/{company_id}/products/{product_id}/supplier-offerings", "GET", ["products.view", "suppliers.view"]),
        ("/companies/{company_id}/suppliers/{supplier_id}/product-offerings", "POST", ["products.view", "suppliers.view"]),
        ("/companies/{company_id}/supplier-payables/payments", "GET", ["payments.view"]),
        ("/companies/{company_id}/supplier-payables/payments", "POST", ["payments.create"]),
        ("/companies/{company_id}/sites/{site_id}/daily-closings", "GET", ["cash_drawer.view", "expenses.view", "payments.view", "sales.view", "sales_returns.view", "supplier_payables.view"]),
        ("/companies/{company_id}/sites/{site_id}/daily-closings/{closing_id}", "GET", ["cash_drawer.view", "expenses.view", "payments.view", "sales.view", "sales_returns.view", "supplier_payables.view"]),
        ("/companies/{company_id}/sites/{site_id}/daily-closings", "POST", ["cash_drawer.view", "expenses.view", "payments.view", "sales.view", "sales_returns.view", "supplier_payables.view"]),
        ("/companies/{company_id}/sites/{site_id}/operational-report", "GET", ["cash_drawer.view", "customer_orders.view", "expenses.view", "payments.view", "sales.view", "sales_returns.view", "supplier_payables.view"]),
        ("/companies/{company_id}/inventory/stock", "GET", ["products.view"]),
        ("/companies/{company_id}/inventory/movements", "GET", ["products.view"]),
    ],
)

def test_cross_module_business_operations_require_dependent_permissions(path, method, expected):
    assert additional_permissions_for_request(path, method) == expected


def test_authorization_requires_all_scope_grants_for_cross_module_side_effects(db):
    company, _user, _membership, token = seed_member(db, role="OWNER")
    role = db.scalar(
        __import__("sqlalchemy").select(CompanyRole).where(
            CompanyRole.company_id == company.id,
            CompanyRole.code == "OWNER",
        )
    )
    customer_create = Permission(
        code="customer_orders.create",
        resource_code="customer_orders",
        action_code="create",
        name="客訂-新增",
        is_active=True,
    )
    payment_create = Permission(
        code="payments.create",
        resource_code="payments",
        action_code="create",
        name="收付款-新增",
        is_active=True,
    )
    payment_view = Permission(
        code="payments.view",
        resource_code="payments",
        action_code="view",
        name="收付款-查看",
        is_active=True,
    )
    db.add_all([customer_create, payment_create, payment_view])
    db.flush()
    db.add_all([
        CompanyRolePermission(
            role_id=role.id, permission_id=customer_create.id,
            is_allowed=True, data_scope="OWN",
        ),
        CompanyRolePermission(
            role_id=role.id, permission_id=payment_create.id,
            is_allowed=True, data_scope="OWN",
        ),
        CompanyRolePermission(
            role_id=role.id, permission_id=payment_view.id,
            is_allowed=True, data_scope="ALL",
        ),
    ])
    db.commit()

    with pytest.raises(HTTPException) as exc:
        authorize_google_company_request(
            db, token, company.id, "POST",
            path=f"/companies/{company.id}/customer-orders",
        )
    assert exc.value.status_code == 403
    assert "全公司資料範圍" in exc.value.detail

    payment_grant = db.scalar(
        __import__("sqlalchemy").select(CompanyRolePermission).where(
            CompanyRolePermission.role_id == role.id,
            CompanyRolePermission.permission_id == payment_create.id,
        )
    )
    payment_grant.data_scope = "ALL"
    db.commit()

    grant = authorize_google_company_request(
        db, token, company.id, "POST",
        path=f"/companies/{company.id}/customer-orders",
    )
    # The primary customer-order create permission may still be OWN-scoped,
    # while the dependent payment write must be explicitly ALL-scoped.
    assert grant["permission_code"] == "customer_orders.create"
    assert grant["data_scope"] == "OWN"



@pytest.mark.parametrize("endpoint", ["cash-deposits", "cash-withdrawals"])
def test_bank_cash_operations_require_cash_drawer_create_all_scope(db, endpoint):
    company, _user, _membership, token = seed_member(db, role="STAFF")
    role = db.query(CompanyRole).filter_by(company_id=company.id, code="STAFF").one()
    bank_create = Permission(
        code="bank_accounts.create",
        resource_code="bank_accounts",
        action_code="create",
        name="銀行帳戶－新增",
        is_active=True,
    )
    cash_drawer_create = Permission(
        code="cash_drawer.create",
        resource_code="cash_drawer",
        action_code="create",
        name="現金櫃－新增",
        is_active=True,
    )
    db.add_all([bank_create, cash_drawer_create])
    db.flush()
    db.add_all([
        CompanyRolePermission(
            role_id=role.id, permission_id=bank_create.id,
            is_allowed=True, data_scope="ALL",
        ),
        CompanyRolePermission(
            role_id=role.id, permission_id=cash_drawer_create.id,
            is_allowed=False, data_scope="ALL",
        ),
    ])
    db.commit()

    path = f"/companies/{company.id}/bank-accounts/{uuid4()}/{endpoint}"
    with pytest.raises(HTTPException) as exc:
        authorize_google_company_request(db, token, company.id, "POST", path=path)
    assert exc.value.status_code == 403
    assert "cash_drawer.create" in exc.value.detail

    cash_drawer_grant = db.query(CompanyRolePermission).filter_by(
        role_id=role.id, permission_id=cash_drawer_create.id,
    ).one()
    cash_drawer_grant.is_allowed = True
    db.commit()

    grant = authorize_google_company_request(db, token, company.id, "POST", path=path)
    assert grant["permission_code"] == "bank_accounts.create"



def test_payload_dependent_expense_payment_requires_all_scope_payment_permission(db):
    company, user, membership, _token = seed_member(db, role="STAFF")
    payment = Permission(
        code="payments.create",
        resource_code="payments",
        action_code="create",
        name="收付款-新增",
        is_active=True,
    )
    role = db.scalar(
        __import__("sqlalchemy").select(CompanyRole).where(
            CompanyRole.company_id == company.id,
            CompanyRole.code == "STAFF",
        )
    )
    db.add(payment)
    db.flush()
    grant = CompanyRolePermission(
        role_id=role.id, permission_id=payment.id,
        is_allowed=True, data_scope="OWN",
    )
    db.add(grant)
    db.commit()

    token = current_actor.set(ActorContext(
        actor_type="GOOGLE",
        user_id=user.id,
        company_id=company.id,
        membership_id=membership.id,
        data_scope="ALL",
        permission_code="expenses.create",
    ))
    try:
        with pytest.raises(HTTPException) as exc:
            require_current_actor_permission(db, "payments.create")
        assert exc.value.status_code == 403
        assert "全公司資料範圍" in exc.value.detail

        grant.data_scope = "ALL"
        db.commit()
        require_current_actor_permission(db, "payments.create")
    finally:
        current_actor.reset(token)


def test_owner_admin_actor_can_perform_payload_dependent_payment_action(db):
    token = current_actor.set(ActorContext(
        actor_type="ADMIN",
        admin_username="owner",
    ))
    try:
        require_current_actor_permission(db, "payments.create")
    finally:
        current_actor.reset(token)
