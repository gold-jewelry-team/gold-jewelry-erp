"""Fine-grained authorization for Google member sessions."""
import hashlib
import re
from datetime import datetime, timezone
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

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


COMPANY_PATH_RE = re.compile(
    r"^/companies/(?P<company_id>[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-"
    r"[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12})(?:/|$)"
)

VOID_ENDPOINTS = {"void", "cancel", "deactivate", "reject"}
UPDATE_ENDPOINTS = {"submit", "receive", "complete", "review", "match", "ignore", "approve", "suspend", "reactivate", "status", "retry", "restore", "pay"}
# OWN is deliberately limited to independent transaction lists. Shared master
# data, balances, reconciliation, and aggregate reports must remain ALL-scoped.
OWN_SCOPE_RESOURCES = {
    "purchases",
    "sales",
    "customer_orders",
    "expenses",
}

RESOURCE_ROOTS = {
    "products": "products",
    "product-categories": "product_categories",
    "inventory": "inventory",
    "purchases": "purchases",
    "customer-orders": "customer_orders",
    "suppliers": "suppliers",
    "supplier-payables": "supplier_payables",
    "operating-expenses": "expenses",
    "gold-material": "gold_material",
    "gold-prices": "gold_prices",
    "supplier-category-offerings": "supplier_offerings",
    "supplier-product-offerings": "supplier_offerings",
    "labor-code-config": "product_code_settings",
    "product-code-sequence": "product_code_settings",
    "operational-report": "reports",
    "reports": "reports",
}


def company_id_from_path(path: str) -> UUID | None:
    """Return a canonical company UUID only for company-scoped API paths."""
    match = COMPANY_PATH_RE.match(path)
    if not match:
        return None
    try:
        return UUID(match.group("company_id"))
    except ValueError:
        return None


def permission_for_request(path: str, method: str) -> str:
    """Resolve an allow-listed company API path to one permission catalog code."""
    parts = [part for part in path.strip("/").split("/") if part]
    if len(parts) < 3 or parts[0] != "companies":
        raise HTTPException(status_code=403, detail="此 API 尚未設定公司成員權限。")
    tail = parts[2:]
    root = tail[0]

    if any(part in {"category-offerings", "product-offerings", "supplier-offerings"} for part in tail):
        resource = "supplier_offerings"
    elif root == "sales":
        if "payments" in tail:
            resource = "payments"
        elif "returns" in tail:
            resource = "sales_returns"
        else:
            resource = "sales"
    elif root == "customer-orders" and any(
        part in {"payments", "refunds"} for part in tail
    ):
        resource = "payments"
    elif root == "bank-accounts":
        resource = (
            "bank_reconciliation"
            if "statement-imports" in tail or "reconciliation-snapshots" in tail or "reconciliation-report" in tail
            else "bank_accounts"
        )
    elif root == "sites":
        if "cash-drawer-movements" in tail:
            resource = "cash_drawer"
        elif "operational-report" in tail:
            resource = "reports"
        elif "daily-closings" in tail or "cash-count" in tail:
            resource = "daily_closing"
        else:
            resource = "company_settings"
    elif root == "daily-closings":
        resource = "daily_closing"
    elif root == "cash-drawer-movements":
        resource = "cash_drawer"
    else:
        resource = RESOURCE_ROOTS.get(root)

    if resource is None:
        raise HTTPException(
            status_code=403,
            detail="此功能尚未納入公司成員權限目錄，暫不開放。",
        )

    normalized_method = method.upper()
    endpoint = tail[-1]
    if normalized_method in {"GET", "HEAD", "OPTIONS"}:
        action = "view"
    elif normalized_method in {"PUT", "PATCH"}:
        action = "update"
    elif normalized_method == "DELETE":
        action = "void"
    elif normalized_method == "POST":
        if endpoint in VOID_ENDPOINTS:
            action = "void"
        elif endpoint in UPDATE_ENDPOINTS:
            action = "update"
        else:
            action = "create"
    else:
        raise HTTPException(status_code=403, detail="不支援此 API 操作方式。")

    return f"{resource}.{action}"


def authorize_google_company_request(
    db: Session,
    raw_session_token: str,
    company_id: UUID,
    method: str,
    *,
    path: str | None = None,
    now: datetime | None = None,
) -> dict:
    """Validate session, exact-company membership, role permission, and data scope."""
    if not raw_session_token:
        raise HTTPException(status_code=401, detail="請先使用已核准的 Google 帳號登入。")

    token_hash = hashlib.sha256(raw_session_token.encode("utf-8")).hexdigest()
    current_time = now or datetime.now(timezone.utc)
    session = db.scalar(
        select(UserSession).where(
            UserSession.token_hash == token_hash,
            UserSession.revoked_at.is_(None),
            UserSession.expires_at > current_time,
        )
    )
    if session is None:
        raise HTTPException(status_code=401, detail="Google 登入已失效，請重新登入。")

    user = db.get(User, session.user_id)
    if user is None or not user.is_active:
        raise HTTPException(status_code=403, detail="此使用者帳號已停用。")

    company = db.get(Company, company_id)
    if company is None or not company.is_active:
        raise HTTPException(status_code=404, detail="找不到啟用中的公司。")

    membership = db.scalar(
        select(CompanyMembership).where(
            CompanyMembership.user_id == user.id,
            CompanyMembership.company_id == company_id,
            CompanyMembership.status == "ACTIVE",
        )
    )
    if membership is None:
        raise HTTPException(
            status_code=403,
            detail="此 Google 帳號尚未獲准使用這間公司的資料。",
        )

    request_path = path or f"/companies/{company_id}/products"
    permission_code = permission_for_request(request_path, method)
    grants = db.execute(
        select(CompanyRolePermission.is_allowed, CompanyRolePermission.data_scope)
        .join(CompanyMembershipRole, CompanyMembershipRole.role_id == CompanyRolePermission.role_id)
        .join(CompanyRole, CompanyRole.id == CompanyMembershipRole.role_id)
        .join(Permission, Permission.id == CompanyRolePermission.permission_id)
        .where(
            CompanyMembershipRole.membership_id == membership.id,
            CompanyRole.company_id == company_id,
            CompanyRole.is_active.is_(True),
            Permission.code == permission_code,
            Permission.is_active.is_(True),
        )
    ).all()

    allowed_grants = [(allowed, scope) for allowed, scope in grants if allowed]
    if not allowed_grants:
        raise HTTPException(
            status_code=403,
            detail=f"此角色未獲授權執行「{permission_code}」。",
        )

    # Multiple roles are additive: ALL is the broadest scope among allowed grants.
    scope = "ALL" if any(value == "ALL" for _allowed, value in allowed_grants) else "OWN"
    if scope == "OWN":
        resource_code, action_code = permission_code.split(".", 1)
        if resource_code not in OWN_SCOPE_RESOURCES or action_code not in {"view", "create"}:
            raise HTTPException(
                status_code=403,
                detail="本人資料範圍目前僅支援查看與新增；此操作暫不開放。",
            )

    return {
        "user_id": user.id,
        "display_name": user.display_name,
        "company_id": company.id,
        "company_name": company.name,
        "membership_id": membership.id,
        "role": membership.role,
        "permission_code": permission_code,
        "data_scope": scope,
    }
