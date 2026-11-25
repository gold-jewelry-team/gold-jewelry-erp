"""Company-scoped custom roles and fine-grained permission assignments."""
import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean, CheckConstraint, DateTime, ForeignKey, Index, String,
    UniqueConstraint, Uuid, func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class Permission(Base):
    """Stable application permission catalog, e.g. products.view."""

    __tablename__ = "permissions"
    __table_args__ = (
        UniqueConstraint("code", name="uq_permissions_code"),
        CheckConstraint(
            "action_code IN ('view', 'create', 'update', 'void')",
            name="ck_permissions_action_code",
        ),
        Index("ix_permissions_resource_action", "resource_code", "action_code"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    code: Mapped[str] = mapped_column(String(100), nullable=False)
    resource_code: Mapped[str] = mapped_column(String(50), nullable=False)
    action_code: Mapped[str] = mapped_column(String(20), nullable=False)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default="true")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())


class CompanyRole(Base):
    """A built-in or owner-customized role within one company."""

    __tablename__ = "company_roles"
    __table_args__ = (
        UniqueConstraint("company_id", "code", name="uq_company_roles_company_code"),
        CheckConstraint("length(code) > 0", name="ck_company_roles_code_nonempty"),
        Index("ix_company_roles_company_active", "company_id", "is_active"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    company_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), ForeignKey("companies.id", ondelete="RESTRICT"), nullable=False)
    code: Mapped[str] = mapped_column(String(40), nullable=False)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    description: Mapped[str | None] = mapped_column(String(500), nullable=True)
    is_system: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="false")
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default="true")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())


class CompanyRolePermission(Base):
    """Allow/deny one catalog permission and define its row data scope."""

    __tablename__ = "company_role_permissions"
    __table_args__ = (
        UniqueConstraint("role_id", "permission_id", name="uq_company_role_permissions_role_permission"),
        CheckConstraint("data_scope IN ('ALL', 'OWN')", name="ck_company_role_permissions_data_scope"),
        Index("ix_company_role_permissions_role_allowed", "role_id", "is_allowed"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    role_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), ForeignKey("company_roles.id", ondelete="CASCADE"), nullable=False)
    permission_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), ForeignKey("permissions.id", ondelete="RESTRICT"), nullable=False)
    is_allowed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="false")
    data_scope: Mapped[str] = mapped_column(String(10), nullable=False, default="OWN", server_default="OWN")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())


class CompanyMembershipRole(Base):
    """Many-to-many role assignment; one member may hold several company roles."""

    __tablename__ = "company_membership_roles"
    __table_args__ = (
        UniqueConstraint("membership_id", "role_id", name="uq_company_membership_roles_membership_role"),
        Index("ix_company_membership_roles_role_id", "role_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    membership_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), ForeignKey("company_memberships.id", ondelete="CASCADE"), nullable=False)
    role_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), ForeignKey("company_roles.id", ondelete="RESTRICT"), nullable=False)
    assigned_by_user_id: Mapped[uuid.UUID | None] = mapped_column(Uuid(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
