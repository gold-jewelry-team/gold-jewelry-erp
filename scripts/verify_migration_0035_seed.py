"""Verify Alembic 0035 data backfill on a disposable PostgreSQL CI database.

Usage:
  python scripts/verify_migration_0035_seed.py seed
  python scripts/verify_migration_0035_seed.py verify
"""
import argparse
import os
from sqlalchemy import create_engine, text


COMPANY_A = "f0000000-0000-4000-8000-000000000001"
COMPANY_B = "f0000000-0000-4000-8000-000000000002"
USER_STAFF = "f0000000-0000-4000-8000-000000000011"
USER_MANAGER = "f0000000-0000-4000-8000-000000000012"
USER_OWNER = "f0000000-0000-4000-8000-000000000013"
MEMBERSHIP_STAFF = "f0000000-0000-4000-8000-000000000021"
MEMBERSHIP_MANAGER = "f0000000-0000-4000-8000-000000000022"
MEMBERSHIP_OWNER = "f0000000-0000-4000-8000-000000000023"
EXPECTED_RESOURCES = 24
EXPECTED_ACTIONS = 4


def _engine():
    database_url = os.environ.get("DATABASE_URL", "").strip()
    if not database_url:
        raise RuntimeError("DATABASE_URL is required for this CI-only migration test.")
    if "-pooler" in database_url.split("@", 1)[-1].split("/", 1)[0]:
        raise RuntimeError("Migration verification must use a direct PostgreSQL connection.")
    return create_engine(database_url)


def seed():
    engine = _engine()
    try:
        with engine.begin() as connection:
            # Keep this fixture repeatable when the CI database is reused.
            connection.execute(text(
                "DELETE FROM company_memberships WHERE id IN "
                "(:staff_id, :manager_id, :owner_id)"
            ), {
                "staff_id": MEMBERSHIP_STAFF,
                "manager_id": MEMBERSHIP_MANAGER,
                "owner_id": MEMBERSHIP_OWNER,
            })
            connection.execute(text(
                "DELETE FROM users WHERE id IN (:staff_id, :manager_id, :owner_id)"
            ), {
                "staff_id": USER_STAFF,
                "manager_id": USER_MANAGER,
                "owner_id": USER_OWNER,
            })
            connection.execute(text(
                "DELETE FROM companies WHERE id IN (:company_a, :company_b)"
            ), {"company_a": COMPANY_A, "company_b": COMPANY_B})

            connection.execute(text("""
                INSERT INTO companies (id, code, name, is_active)
                VALUES
                    (:company_a, 'MIGTEST_A', 'Migration 測試甲公司', true),
                    (:company_b, 'MIGTEST_B', 'Migration 測試乙公司', true)
            """), {"company_a": COMPANY_A, "company_b": COMPANY_B})
            connection.execute(text("""
                INSERT INTO users (id, display_name, email, is_active)
                VALUES
                    (:staff_id, '測試一般成員', 'migration-staff@example.invalid', true),
                    (:manager_id, '測試管理者', 'migration-manager@example.invalid', true),
                    (:owner_id, '測試負責人', 'migration-owner@example.invalid', true)
            """), {
                "staff_id": USER_STAFF,
                "manager_id": USER_MANAGER,
                "owner_id": USER_OWNER,
            })
            connection.execute(text("""
                INSERT INTO company_memberships
                    (id, company_id, user_id, status, role)
                VALUES
                    (:staff_membership, :company_a, :staff_id, 'PENDING', 'STAFF'),
                    (:manager_membership, :company_a, :manager_id, 'ACTIVE', 'MANAGER'),
                    (:owner_membership, :company_b, :owner_id, 'ACTIVE', 'OWNER')
            """), {
                "staff_membership": MEMBERSHIP_STAFF,
                "manager_membership": MEMBERSHIP_MANAGER,
                "owner_membership": MEMBERSHIP_OWNER,
                "company_a": COMPANY_A,
                "company_b": COMPANY_B,
                "staff_id": USER_STAFF,
                "manager_id": USER_MANAGER,
                "owner_id": USER_OWNER,
            })
        print("Seeded two companies and three memberships at schema revision 0034.")
    finally:
        engine.dispose()


def verify():
    engine = _engine()
    try:
        with engine.connect() as connection:
            permission_count = connection.execute(text(
                "SELECT count(*) FROM permissions WHERE is_active = true"
            )).scalar_one()
            expected_permission_count = EXPECTED_RESOURCES * EXPECTED_ACTIONS
            assert permission_count == expected_permission_count, (
                f"Expected {expected_permission_count} permissions, got {permission_count}"
            )

            role_count = connection.execute(text("""
                SELECT count(*) FROM company_roles
                WHERE company_id IN (:company_a, :company_b)
            """), {"company_a": COMPANY_A, "company_b": COMPANY_B}).scalar_one()
            assert role_count == 6, f"Expected six company roles, got {role_count}"

            permission_grant_count = connection.execute(text("""
                SELECT count(*)
                FROM company_role_permissions rp
                JOIN company_roles r ON r.id = rp.role_id
                WHERE r.company_id IN (:company_a, :company_b)
            """), {"company_a": COMPANY_A, "company_b": COMPANY_B}).scalar_one()
            expected_grants = 6 * expected_permission_count
            assert permission_grant_count == expected_grants, (
                f"Expected {expected_grants} permission grants, got {permission_grant_count}"
            )

            expected_memberships = {
                MEMBERSHIP_STAFF: ("STAFF", "OWN", False),
                MEMBERSHIP_MANAGER: ("MANAGER", "ALL", True),
                MEMBERSHIP_OWNER: ("OWNER", "ALL", True),
            }
            association_rows = connection.execute(text("""
                SELECT cmr.membership_id, cr.code, cr.company_id
                FROM company_membership_roles cmr
                JOIN company_roles cr ON cr.id = cmr.role_id
                WHERE cmr.membership_id IN (
                    :staff_membership, :manager_membership, :owner_membership
                )
            """), {
                "staff_membership": MEMBERSHIP_STAFF,
                "manager_membership": MEMBERSHIP_MANAGER,
                "owner_membership": MEMBERSHIP_OWNER,
            }).all()
            actual = {str(row.membership_id): (row.code, str(row.company_id)) for row in association_rows}
            assert len(actual) == 3, f"Expected three membership-role links, got {len(actual)}"
            assert actual[MEMBERSHIP_STAFF] == ("STAFF", COMPANY_A)
            assert actual[MEMBERSHIP_MANAGER] == ("MANAGER", COMPANY_A)
            assert actual[MEMBERSHIP_OWNER] == ("OWNER", COMPANY_B)

            baseline = connection.execute(text("""
                SELECT r.code, p.action_code, rp.is_allowed, rp.data_scope
                FROM company_roles r
                JOIN company_role_permissions rp ON rp.role_id = r.id
                JOIN permissions p ON p.id = rp.permission_id
                WHERE r.company_id = :company_id
                  AND p.code = 'products.view'
            """), {"company_id": COMPANY_A}).all()
            baseline_by_role = {
                row.code: (row.action_code, row.is_allowed, row.data_scope)
                for row in baseline
            }
            assert baseline_by_role == {
                "OWNER": ("view", True, "ALL"),
                "MANAGER": ("view", True, "ALL"),
                "STAFF": ("view", False, "OWN"),
            }, f"Unexpected default role baselines: {baseline_by_role}"

            manager_writes = connection.execute(text("""
                SELECT count(*)
                FROM company_role_permissions rp
                JOIN company_roles r ON r.id = rp.role_id
                JOIN permissions p ON p.id = rp.permission_id
                WHERE r.company_id = :company_id
                  AND r.code = 'MANAGER'
                  AND p.action_code <> 'view'
                  AND rp.is_allowed = true
            """), {"company_id": COMPANY_A}).scalar_one()
            assert manager_writes == 0, "MANAGER must be read-only by default"

            staff_allowed = connection.execute(text("""
                SELECT count(*)
                FROM company_role_permissions rp
                JOIN company_roles r ON r.id = rp.role_id
                WHERE r.company_id = :company_id
                  AND r.code = 'STAFF'
                  AND rp.is_allowed = true
            """), {"company_id": COMPANY_A}).scalar_one()
            assert staff_allowed == 0, "STAFF must have no permissions by default"

        print(
            "Migration 0035 data backfill passed: "
            "24 resources × 4 actions, six company roles, "
            "576 grants, and three correct membership-role links."
        )
    finally:
        engine.dispose()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=("seed", "verify"))
    args = parser.parse_args()
    seed() if args.command == "seed" else verify()
