"""Helpers for initializing company roles and replacing membership assignments."""
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.models import (
    CompanyMembership,
    CompanyMembershipRole,
    CompanyRole,
    CompanyRolePermission,
    Permission,
)


SYSTEM_ROLES = {
    "OWNER": ("負責人", "公司內完整管理權限"),
    "MANAGER": ("管理者", "預設唯讀，依職務調整"),
    "STAFF": ("一般成員", "預設不授權，待建立者追蹤完成後設定"),
}


def ensure_company_system_roles(db: Session, company_id) -> dict[str, CompanyRole]:
    """Create default role definitions and their safe baseline grants for a company."""
    permissions = list(db.scalars(
        select(Permission).where(Permission.is_active.is_(True)).order_by(Permission.code)
    ).all())
    roles: dict[str, CompanyRole] = {}
    for code, (name, description) in SYSTEM_ROLES.items():
        role = db.scalar(select(CompanyRole).where(
            CompanyRole.company_id == company_id,
            CompanyRole.code == code,
        ))
        if role is None:
            role = CompanyRole(
                company_id=company_id,
                code=code,
                name=name,
                description=description,
                is_system=True,
                is_active=True,
            )
            db.add(role)
            db.flush()
        roles[code] = role

        existing_permission_ids = set(db.scalars(
            select(CompanyRolePermission.permission_id).where(
                CompanyRolePermission.role_id == role.id
            )
        ).all())
        for permission in permissions:
            if permission.id in existing_permission_ids:
                continue
            allowed = code == "OWNER" or (
                code == "MANAGER" and permission.action_code == "view"
            )
            db.add(CompanyRolePermission(
                role_id=role.id,
                permission_id=permission.id,
                is_allowed=allowed,
                data_scope="OWN" if code == "STAFF" else "ALL",
            ))
    return roles


def replace_membership_roles(
    db: Session,
    membership: CompanyMembership,
    role_codes: list[str],
) -> list[CompanyMembershipRole]:
    """Replace all role grants for a membership with company-local active roles."""
    normalized = list(dict.fromkeys(code.strip().upper() for code in role_codes if code.strip()))
    if not normalized:
        raise ValueError("至少要指定一個角色。")

    system_roles = ensure_company_system_roles(db, membership.company_id)
    selected_roles: list[CompanyRole] = []
    for code in normalized:
        role = system_roles.get(code) or db.scalar(select(CompanyRole).where(
            CompanyRole.company_id == membership.company_id,
            CompanyRole.code == code,
            CompanyRole.is_active.is_(True),
        ))
        if role is None or not role.is_active:
            raise ValueError(f"找不到啟用中的角色：{code}")
        selected_roles.append(role)

    db.execute(delete(CompanyMembershipRole).where(
        CompanyMembershipRole.membership_id == membership.id
    ))
    rows = [
        CompanyMembershipRole(membership_id=membership.id, role_id=role.id)
        for role in selected_roles
    ]
    db.add_all(rows)
    # Keep the legacy role column synchronized for older clients and reports.
    membership.role = selected_roles[0].code if selected_roles[0].code in SYSTEM_ROLES else "STAFF"
    return rows


def replace_membership_role_ids(
    db: Session,
    membership: CompanyMembership,
    role_ids: list,
) -> list[CompanyMembershipRole]:
    """Assign one or more role IDs, validating every role belongs to the same company."""
    unique_ids = list(dict.fromkeys(role_ids))
    if not unique_ids:
        raise ValueError("至少要指定一個角色。")
    queried_roles = list(db.scalars(select(CompanyRole).where(
        CompanyRole.id.in_(unique_ids),
        CompanyRole.company_id == membership.company_id,
        CompanyRole.is_active.is_(True),
    )).all())
    role_by_id = {role.id: role for role in queried_roles}
    if len(role_by_id) != len(unique_ids):
        raise ValueError("角色不存在、已停用，或不屬於此公司。")
    roles = [role_by_id[role_id] for role_id in unique_ids]
    db.execute(delete(CompanyMembershipRole).where(
        CompanyMembershipRole.membership_id == membership.id
    ))
    rows = [
        CompanyMembershipRole(membership_id=membership.id, role_id=role.id)
        for role in roles
    ]
    db.add_all(rows)
    membership.role = roles[0].code if roles[0].code in SYSTEM_ROLES else "STAFF"
    return rows
