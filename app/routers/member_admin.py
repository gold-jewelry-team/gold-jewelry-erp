"""Administrator-only Google member approval and lifecycle management API."""
from datetime import datetime, timezone
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.db.session import SessionLocal
from app.models import AuthIdentity, Company, CompanyMembership, User, UserSession

router = APIRouter(prefix="/admin/api", tags=["member-administration"])


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


class AssignMembershipRequest(BaseModel):
    company_id: UUID
    role: Literal["OWNER", "MANAGER", "STAFF"] = "STAFF"


class MembershipActionRequest(BaseModel):
    action: Literal["APPROVE", "REJECT", "SUSPEND", "REACTIVATE"]
    role: Literal["OWNER", "MANAGER", "STAFF"] | None = None


class UserActivationRequest(BaseModel):
    is_active: bool


@router.get("/members")
def list_members(db: Session = Depends(get_db)) -> list[dict]:
    users = list(db.scalars(select(User).order_by(User.created_at.desc())).all())
    result = []
    for user in users:
        identities = list(db.scalars(
            select(AuthIdentity).where(AuthIdentity.user_id == user.id)
        ).all())
        rows = db.execute(
            select(CompanyMembership, Company.name)
            .join(Company, Company.id == CompanyMembership.company_id)
            .where(CompanyMembership.user_id == user.id)
            .order_by(Company.name)
        ).all()
        memberships = [{
            "id": str(membership.id),
            "company_id": str(membership.company_id),
            "company_name": company_name,
            "status": membership.status,
            "role": membership.role,
            "approved_at": membership.approved_at.isoformat() if membership.approved_at else None,
            "created_at": membership.created_at.isoformat() if membership.created_at else None,
        } for membership, company_name in rows]
        result.append({
            "id": str(user.id),
            "display_name": user.display_name,
            "email": user.email,
            "is_active": user.is_active,
            "created_at": user.created_at.isoformat() if user.created_at else None,
            "identities": [{
                "provider": identity.provider,
                "email": identity.provider_email,
                "email_verified": identity.email_verified,
            } for identity in identities],
            "memberships": memberships,
        })
    return result


@router.get("/companies")
def list_active_companies(db: Session = Depends(get_db)) -> list[dict]:
    companies = db.scalars(
        select(Company).where(Company.is_active.is_(True)).order_by(Company.name)
    ).all()
    return [{"id": str(company.id), "name": company.name, "code": company.code} for company in companies]


@router.post("/users/{user_id}/memberships", status_code=201)
def assign_company(user_id: UUID, payload: AssignMembershipRequest, db: Session = Depends(get_db)) -> dict:
    user = db.get(User, user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="找不到此 Google 使用者。")
    if not user.is_active:
        raise HTTPException(status_code=409, detail="此使用者已停用，請先重新啟用帳號。")
    company = db.get(Company, payload.company_id)
    if company is None or not company.is_active:
        raise HTTPException(status_code=422, detail="只能指定啟用中的公司。")

    membership = db.scalar(select(CompanyMembership).where(
        CompanyMembership.user_id == user_id,
        CompanyMembership.company_id == payload.company_id,
    ))
    if membership is None:
        membership = CompanyMembership(
            user_id=user_id, company_id=payload.company_id,
            status="PENDING", role=payload.role,
        )
        db.add(membership)
    elif membership.status == "REJECTED":
        membership.status = "PENDING"
        membership.role = payload.role
        membership.approved_at = None
        membership.approved_by_user_id = None
    elif membership.status == "PENDING":
        membership.role = payload.role
    else:
        raise HTTPException(status_code=409, detail="此使用者已存在有效或暫停中的公司成員關係。")

    db.commit()
    db.refresh(membership)
    return {
        "id": str(membership.id), "user_id": str(user_id),
        "company_id": str(payload.company_id), "status": membership.status,
        "role": membership.role,
    }


@router.patch("/memberships/{membership_id}")
def update_membership(
    membership_id: UUID,
    payload: MembershipActionRequest,
    db: Session = Depends(get_db),
) -> dict:
    membership = db.get(CompanyMembership, membership_id)
    if membership is None:
        raise HTTPException(status_code=404, detail="找不到此公司成員申請。")
    user = db.get(User, membership.user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="找不到此使用者。")

    allowed = {
        "APPROVE": {"PENDING"},
        "REJECT": {"PENDING"},
        "SUSPEND": {"ACTIVE"},
        "REACTIVATE": {"SUSPENDED"},
    }
    if membership.status not in allowed[payload.action]:
        raise HTTPException(status_code=409, detail="目前成員狀態不允許此操作。")

    if payload.action == "APPROVE":
        company = db.get(Company, membership.company_id)
        if company is None or not company.is_active:
            raise HTTPException(status_code=409, detail="所屬公司已停用，無法核准。")
        if not user.is_active:
            raise HTTPException(status_code=409, detail="使用者帳號已停用，無法核准。")
        membership.status = "ACTIVE"
        membership.approved_at = datetime.now(timezone.utc)
        if payload.role:
            membership.role = payload.role
    elif payload.action == "REJECT":
        membership.status = "REJECTED"
    elif payload.action == "SUSPEND":
        membership.status = "SUSPENDED"
    elif payload.action == "REACTIVATE":
        company = db.get(Company, membership.company_id)
        if company is None or not company.is_active or not user.is_active:
            raise HTTPException(status_code=409, detail="使用者或公司已停用，無法恢復。")
        membership.status = "ACTIVE"

    has_other_active_membership = db.scalar(select(CompanyMembership.id).where(
        CompanyMembership.user_id == user.id,
        CompanyMembership.id != membership.id,
        CompanyMembership.status == "ACTIVE",
    ).limit(1))
    if payload.action in {"REJECT", "SUSPEND"} and has_other_active_membership is None:
        db.execute(
            update(UserSession)
            .where(UserSession.user_id == user.id, UserSession.revoked_at.is_(None))
            .values(revoked_at=datetime.now(timezone.utc))
        )

    db.commit()
    db.refresh(membership)
    return {
        "id": str(membership.id), "user_id": str(user.id),
        "company_id": str(membership.company_id),
        "status": membership.status, "role": membership.role,
    }


@router.patch("/users/{user_id}")
def update_user_activation(
    user_id: UUID,
    payload: UserActivationRequest,
    db: Session = Depends(get_db),
) -> dict:
    user = db.get(User, user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="找不到此使用者。")
    user.is_active = payload.is_active
    if not payload.is_active:
        db.execute(
            update(UserSession)
            .where(UserSession.user_id == user.id, UserSession.revoked_at.is_(None))
            .values(revoked_at=datetime.now(timezone.utc))
        )
    db.commit()
    return {"id": str(user.id), "is_active": user.is_active}
