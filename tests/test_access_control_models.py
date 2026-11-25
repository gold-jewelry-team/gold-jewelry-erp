from sqlalchemy import UniqueConstraint

from app.db.base import Base
from app import models  # noqa: F401
from app.models.access_control import (
    CompanyMembershipRole,
    CompanyRole,
    CompanyRolePermission,
    Permission,
)


def _unique_names(table):
    return {
        constraint.name
        for constraint in table.constraints
        if isinstance(constraint, UniqueConstraint)
    }


def test_permission_and_company_role_tables_are_registered():
    assert {
        "permissions",
        "company_roles",
        "company_role_permissions",
        "company_membership_roles",
    }.issubset(set(Base.metadata.tables))


def test_permission_catalog_has_stable_resource_action_uniqueness():
    table = Permission.__table__
    assert "uq_permissions_code" in _unique_names(table)
    assert "ck_permissions_action_code" in {
        constraint.name for constraint in table.constraints
    }
    assert table.c.code.type.length == 100


def test_company_roles_are_unique_within_each_company_not_globally():
    table = CompanyRole.__table__
    assert "uq_company_roles_company_code" in _unique_names(table)
    assert table.c.company_id.foreign_keys


def test_role_permissions_store_allow_and_data_scope_independently():
    table = CompanyRolePermission.__table__
    assert "uq_company_role_permissions_role_permission" in _unique_names(table)
    assert "ck_company_role_permissions_data_scope" in {
        constraint.name for constraint in table.constraints
    }
    assert table.c.is_allowed.default.arg is False
    assert table.c.data_scope.default.arg == "OWN"


def test_membership_supports_multiple_roles_without_duplicate_assignment():
    table = CompanyMembershipRole.__table__
    assert "uq_company_membership_roles_membership_role" in _unique_names(table)
    assert table.c.membership_id.foreign_keys
    assert table.c.role_id.foreign_keys
