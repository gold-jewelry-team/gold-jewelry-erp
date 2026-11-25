"""Company-scoped authorization for Google member sessions.

The owner username/password session remains the unrestricted administrator path.
Google members must have an active membership for the exact company in the URL.
The initial role policy is intentionally conservative until configurable permissions
and actor-level data provenance are implemented:
- OWNER: full company API access
- MANAGER: read-only company API access
- STAFF: denied business API access (own-record filtering is not yet possible)
"""
import hashlib
import re
from datetime import datetime, timezone
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Company, CompanyMembership, User, UserSession


COMPANY_PATH_RE = re.compile(
    r"^/companies/(?P<company_id>[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-"
    r"[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12})(?:/|$)"
)

ROLE_METHODS = {
    "OWNER": frozenset({"GET", "HEAD", "OPTIONS", "POST", "PUT", "PATCH", "DELETE"}),
    "MANAGER": frozenset({"GET", "HEAD", "OPTIONS"}),
    # STAFF is denied until actor attribution exists for reliable own-record scopes.
    "STAFF": frozenset(),
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


def authorize_google_company_request(
    db: Session,
    raw_session_token: str,
    company_id: UUID,
    method: str,
    *,
    now: datetime | None = None,
) -> dict:
    """Validate a Google session, active user, exact-company membership and role."""
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

    allowed_methods = ROLE_METHODS.get(membership.role, frozenset())
    if method.upper() not in allowed_methods:
        if membership.role == "STAFF":
            detail = (
                "一般成員的細項權限及僅本人資料範圍尚未完成設定，"
                "目前不開放營運資料存取。"
            )
        else:
            detail = "目前角色沒有執行此操作的權限。"
        raise HTTPException(status_code=403, detail=detail)

    return {
        "user_id": user.id,
        "display_name": user.display_name,
        "company_id": company.id,
        "company_name": company.name,
        "membership_id": membership.id,
        "role": membership.role,
    }
