"""Administrator-only Google member, company role, and permission management API."""
from datetime import datetime, timezone
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import and_, select, update
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Session

from app.db.session import SessionLocal
from app.models import (
    AuthIdentity,
    Company,
    CompanyMembership,
    CompanyMembershipRole,
    CompanyRole,
    CompanyRolePermission,
    Permission,
    User,
    UserSession,
)
from app.services.access_control import (
    ensure_company_system_roles,
    replace_membership_role_ids,
    replace_membership_roles,
)

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


class CompanyRoleCreateRequest(BaseModel):
    code: str = Field(min_length=2, max_length=40, pattern=r"^[A-Z][A-Z0-9_]*$")
    name: str = Field(min_length=1, max_length=100)
    description: str | None = Field(default=None, max_length=500)


class CompanyRoleUpdateRequest(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=100)
    description: str | None = Field(default=None, max_length=500)
    is_active: bool | None = None


class PermissionGrantUpdate(BaseModel):
    code: str = Field(min_length=3, max_length=100)
    is_allowed: bool
    data_scope: Literal["ALL", "OWN"] = "OWN"


class CompanyRolePermissionsUpdate(BaseModel):
    permissions: list[PermissionGrantUpdate] = Field(min_length=1, max_length=200)


class MembershipRolesUpdate(BaseModel):
    role_ids: list[UUID] = Field(min_length=1, max_length=20)


def _ensure_permission_schema(db: Session) -> None:
    try:
        db.scalar(select(Permission.id).limit(1))
        db.scalar(select(CompanyRole.id).limit(1))
    except SQLAlchemyError as exc:
        raise HTTPException(
            status_code=503,
            detail="角色權限資料庫尚未完成 Migration，暫時無法管理權限。",
        ) from exc


def _role_payload(db: Session, role: CompanyRole) -> dict:
    rows = db.execute(
        select(Permission.code, Permission.name, Permission.resource_code,
               Permission.action_code, CompanyRolePermission.is_allowed,
               CompanyRolePermission.data_scope)
        .select_from(Permission)
        .outerjoin(
            CompanyRolePermission,
            and_(
                CompanyRolePermission.permission_id == Permission.id,
                CompanyRolePermission.role_id == role.id,
            ),
        )
        .where(Permission.is_active.is_(True))
        .order_by(Permission.resource_code, Permission.action_code)
    ).all()
    return {
        "id": str(role.id),
        "company_id": str(role.company_id),
        "code": role.code,
        "name": role.name,
        "description": role.description,
        "is_system": role.is_system,
        "is_active": role.is_active,
        "permissions": [{
            "code": code,
            "name": name,
            "resource_code": resource_code,
            "action_code": action_code,
            "is_allowed": bool(is_allowed) if is_allowed is not None else False,
            "data_scope": data_scope or "OWN",
        } for code, name, resource_code, action_code, is_allowed, data_scope in rows],
    }


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
        memberships = []
        for membership, company_name in rows:
            role_rows = db.execute(
                select(CompanyRole.id, CompanyRole.code, CompanyRole.name)
                .join(CompanyMembershipRole, CompanyMembershipRole.role_id == CompanyRole.id)
                .where(CompanyMembershipRole.membership_id == membership.id)
                .order_by(CompanyRole.name)
            ).all()
            memberships.append({
                "id": str(membership.id),
                "company_id": str(membership.company_id),
                "company_name": company_name,
                "status": membership.status,
                "role": membership.role,
                "roles": [{
                    "id": str(role_id), "code": code, "name": name,
                } for role_id, code, name in role_rows],
                "approved_at": membership.approved_at.isoformat() if membership.approved_at else None,
                "created_at": membership.created_at.isoformat() if membership.created_at else None,
            })
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


@router.get("/permissions")
def list_permission_catalog(db: Session = Depends(get_db)) -> list[dict]:
    _ensure_permission_schema(db)
    rows = db.scalars(
        select(Permission).where(Permission.is_active.is_(True)).order_by(
            Permission.resource_code, Permission.action_code
        )
    ).all()
    return [{
        "code": row.code,
        "resource_code": row.resource_code,
        "action_code": row.action_code,
        "name": row.name,
    } for row in rows]


@router.get("/companies/{company_id}/roles")
def list_company_roles(company_id: UUID, db: Session = Depends(get_db)) -> list[dict]:
    _ensure_permission_schema(db)
    company = db.get(Company, company_id)
    if company is None:
        raise HTTPException(status_code=404, detail="找不到指定公司。")
    roles = db.scalars(
        select(CompanyRole).where(CompanyRole.company_id == company_id)
        .order_by(CompanyRole.is_system.desc(), CompanyRole.name)
    ).all()
    return [_role_payload(db, role) for role in roles]


@router.post("/companies/{company_id}/roles", status_code=201)
def create_company_role(
    company_id: UUID,
    payload: CompanyRoleCreateRequest,
    db: Session = Depends(get_db),
) -> dict:
    _ensure_permission_schema(db)
    company = db.get(Company, company_id)
    if company is None or not company.is_active:
        raise HTTPException(status_code=404, detail="找不到啟用中的公司。")
    reserved = {"OWNER", "MANAGER", "STAFF"}
    if payload.code in reserved:
        raise HTTPException(status_code=409, detail="此代碼為系統保留角色。")
    role = CompanyRole(
        company_id=company_id,
        code=payload.code,
        name=payload.name.strip(),
        description=payload.description,
        is_system=False,
        is_active=True,
    )
    db.add(role)
    try:
        db.flush()
        permissions = db.scalars(select(Permission).where(Permission.is_active.is_(True))).all()
        db.add_all([
            CompanyRolePermission(
                role_id=role.id, permission_id=permission.id,
                is_allowed=False, data_scope="OWN",
            )
            for permission in permissions
        ])
        db.commit()
        db.refresh(role)
        return _role_payload(db, role)
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail="角色代碼已存在。") from exc


@router.patch("/roles/{role_id}")
def update_company_role(
    role_id: UUID,
    payload: CompanyRoleUpdateRequest,
    db: Session = Depends(get_db),
) -> dict:
    _ensure_permission_schema(db)
    role = db.get(CompanyRole, role_id)
    if role is None:
        raise HTTPException(status_code=404, detail="找不到指定角色。")
    changes = payload.model_dump(exclude_unset=True)
    if role.is_system and changes.get("is_active") is False:
        raise HTTPException(status_code=409, detail="系統預設角色不可停用。")
    if any(value is None for key, value in changes.items() if key == "name"):
        raise HTTPException(status_code=422, detail="角色名稱不可為空。")
    for key, value in changes.items():
        setattr(role, key, value)
    db.commit()
    db.refresh(role)
    return _role_payload(db, role)


@router.put("/roles/{role_id}/permissions")
def update_company_role_permissions(
    role_id: UUID,
    payload: CompanyRolePermissionsUpdate,
    db: Session = Depends(get_db),
) -> dict:
    _ensure_permission_schema(db)
    role = db.get(CompanyRole, role_id)
    if role is None or not role.is_active:
        raise HTTPException(status_code=404, detail="找不到啟用中的角色。")
    codes = [item.code for item in payload.permissions]
    if len(codes) != len(set(codes)):
        raise HTTPException(status_code=422, detail="同一權限不可重複指定。")
    permission_rows = list(db.scalars(select(Permission).where(
        Permission.code.in_(codes),
        Permission.is_active.is_(True),
    )).all())
    permission_by_code = {item.code: item for item in permission_rows}
    if set(permission_by_code) != set(codes):
        raise HTTPException(status_code=422, detail="權限代碼不存在或已停用。")

    existing = {
        row.permission_id: row
        for row in db.scalars(select(CompanyRolePermission).where(
            CompanyRolePermission.role_id == role.id
        )).all()
    }
    for item in payload.permissions:
        permission = permission_by_code[item.code]
        grant = existing.get(permission.id)
        if grant is None:
            grant = CompanyRolePermission(role_id=role.id, permission_id=permission.id)
            db.add(grant)
        grant.is_allowed = item.is_allowed
        grant.data_scope = item.data_scope
    db.commit()
    db.refresh(role)
    return _role_payload(db, role)


@router.put("/memberships/{membership_id}/roles")
def update_membership_roles(
    membership_id: UUID,
    payload: MembershipRolesUpdate,
    db: Session = Depends(get_db),
) -> dict:
    _ensure_permission_schema(db)
    membership = db.get(CompanyMembership, membership_id)
    if membership is None:
        raise HTTPException(status_code=404, detail="找不到此公司成員關係。")
    try:
        role_rows = replace_membership_role_ids(db, membership, payload.role_ids)
        db.commit()
    except ValueError as exc:
        db.rollback()
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return {
        "membership_id": str(membership.id),
        "role_ids": [str(row.role_id) for row in role_rows],
        "legacy_role": membership.role,
    }


@router.post("/users/{user_id}/memberships", status_code=201)
def assign_company(user_id: UUID, payload: AssignMembershipRequest, db: Session = Depends(get_db)) -> dict:
    _ensure_permission_schema(db)
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
        db.flush()
    elif membership.status == "REJECTED":
        membership.status = "PENDING"
        membership.role = payload.role
        membership.approved_at = None
        membership.approved_by_user_id = None
    elif membership.status == "PENDING":
        membership.role = payload.role
    else:
        raise HTTPException(status_code=409, detail="此使用者已存在有效或暫停中的公司成員關係。")

    try:
        replace_membership_roles(db, membership, [payload.role])
        db.commit()
        db.refresh(membership)
    except (ValueError, SQLAlchemyError) as exc:
        db.rollback()
        raise HTTPException(status_code=503, detail="無法建立公司角色，請確認角色權限 Migration 已完成。") from exc
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
        try:
            replace_membership_roles(db, membership, [membership.role])
        except (ValueError, SQLAlchemyError) as exc:
            db.rollback()
            raise HTTPException(status_code=503, detail="無法套用預設角色，請確認角色權限 Migration 已完成。") from exc
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
