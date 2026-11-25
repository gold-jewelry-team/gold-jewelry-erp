from app.db.base import Base
from app.models.user_identity import AuthIdentity, CompanyMembership, User, UserSession


def test_user_identity_tables_are_registered():
    assert {"users", "auth_identities", "company_memberships", "user_sessions"}.issubset(
        set(Base.metadata.tables)
    )


def test_google_identity_is_unique_by_provider_subject():
    table = AuthIdentity.__table__
    unique_constraints = {constraint.name for constraint in table.constraints if constraint.unique}
    assert "uq_auth_identities_provider_subject" in unique_constraints
    assert "ck_auth_identities_provider" in {constraint.name for constraint in table.constraints}


def test_membership_defaults_to_pending_staff_and_has_scoped_uniqueness():
    table = CompanyMembership.__table__
    assert table.c.status.default.arg == "PENDING"
    assert table.c.role.default.arg == "STAFF"
    assert "uq_company_memberships_company_user" in {
        constraint.name for constraint in table.constraints if constraint.unique
    }
    assert "ck_company_memberships_status" in {
        constraint.name for constraint in table.constraints
    }


def test_sessions_store_token_hash_and_support_revocation():
    table = UserSession.__table__
    assert table.c.token_hash.type.length == 64
    assert table.c.revoked_at.nullable
    assert "uq_user_sessions_token_hash" in {
        constraint.name for constraint in table.constraints if constraint.unique
    }
    assert User.__tablename__ == "users"
