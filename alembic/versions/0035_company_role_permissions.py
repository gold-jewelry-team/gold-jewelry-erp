"""Add company-scoped custom roles and fine-grained permission catalog.

Revision ID: 0035_company_role_permissions
Revises: 0034_user_identity_memberships
Create Date: 2026-11-25
"""
import uuid
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0035_company_role_permissions"
down_revision: Union[str, None] = "0034_user_identity_memberships"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


RESOURCES = (
    ("dashboard", "儀表板"),
    ("products", "商品"),
    ("product_categories", "商品分類"),
    ("inventory", "庫存"),
    ("purchases", "採購"),
    ("sales", "銷售"),
    ("sales_returns", "銷售退貨"),
    ("customer_orders", "客戶訂單"),
    ("suppliers", "供應商"),
    ("supplier_payables", "廠商應付"),
    ("payments", "收付款"),
    ("expenses", "營運費用"),
    ("daily_closing", "每日結帳"),
    ("cash_drawer", "現金櫃"),
    ("bank_accounts", "銀行帳戶"),
    ("bank_reconciliation", "銀行對帳"),
    ("gold_material", "黃金原料"),
    ("gold_prices", "黃金牌價"),
    ("reports", "營運報表"),
    ("company_settings", "公司設定"),
    ("members", "成員管理"),
    ("roles", "角色權限"),
    ("product_code_settings", "商品編碼設定"),
)
ACTIONS = (
    ("view", "查看"),
    ("create", "新增"),
    ("update", "修改"),
    ("void", "作廢"),
)
SYSTEM_ROLES = (
    ("OWNER", "負責人", "公司內完整管理權限"),
    ("MANAGER", "管理者", "預設唯讀，待依實際職務調整"),
    ("STAFF", "一般成員", "預設不授予權限，待建立者追蹤完成後設定"),
)


def upgrade() -> None:
    op.create_table(
        "permissions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("code", sa.String(length=100), nullable=False),
        sa.Column("resource_code", sa.String(length=50), nullable=False),
        sa.Column("action_code", sa.String(length=20), nullable=False),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("is_active", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint(
            "action_code IN ('view', 'create', 'update', 'void')",
            name="ck_permissions_action_code",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("code", name="uq_permissions_code"),
    )
    op.create_index(
        "ix_permissions_resource_action",
        "permissions",
        ["resource_code", "action_code"],
    )

    op.create_table(
        "company_roles",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("company_id", sa.Uuid(), nullable=False),
        sa.Column("code", sa.String(length=40), nullable=False),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column("description", sa.String(length=500), nullable=True),
        sa.Column("is_system", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("is_active", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint("length(code) > 0", name="ck_company_roles_code_nonempty"),
        sa.ForeignKeyConstraint(["company_id"], ["companies.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("company_id", "code", name="uq_company_roles_company_code"),
    )
    op.create_index(
        "ix_company_roles_company_active",
        "company_roles",
        ["company_id", "is_active"],
    )

    op.create_table(
        "company_role_permissions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("role_id", sa.Uuid(), nullable=False),
        sa.Column("permission_id", sa.Uuid(), nullable=False),
        sa.Column("is_allowed", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("data_scope", sa.String(length=10), server_default="OWN", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint("data_scope IN ('ALL', 'OWN')", name="ck_company_role_permissions_data_scope"),
        sa.ForeignKeyConstraint(["role_id"], ["company_roles.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["permission_id"], ["permissions.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("role_id", "permission_id", name="uq_company_role_permissions_role_permission"),
    )
    op.create_index(
        "ix_company_role_permissions_role_allowed",
        "company_role_permissions",
        ["role_id", "is_allowed"],
    )

    op.create_table(
        "company_membership_roles",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("membership_id", sa.Uuid(), nullable=False),
        sa.Column("role_id", sa.Uuid(), nullable=False),
        sa.Column("assigned_by_user_id", sa.Uuid(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["membership_id"], ["company_memberships.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["role_id"], ["company_roles.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["assigned_by_user_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("membership_id", "role_id", name="uq_company_membership_roles_membership_role"),
    )
    op.create_index(
        "ix_company_membership_roles_role_id",
        "company_membership_roles",
        ["role_id"],
    )

    bind = op.get_bind()
    permission_rows = []
    permission_ids = {}
    for resource_code, resource_name in RESOURCES:
        for action_code, action_name in ACTIONS:
            permission_id = uuid.uuid4()
            code = f"{resource_code}.{action_code}"
            permission_ids[code] = permission_id
            permission_rows.append({
                "id": permission_id,
                "code": code,
                "resource_code": resource_code,
                "action_code": action_code,
                "name": f"{resource_name}－{action_name}",
                "is_active": True,
            })
    if permission_rows:
        op.bulk_insert(
            sa.table(
                "permissions",
                sa.column("id", sa.Uuid()),
                sa.column("code", sa.String(100)),
                sa.column("resource_code", sa.String(50)),
                sa.column("action_code", sa.String(20)),
                sa.column("name", sa.String(120)),
                sa.column("is_active", sa.Boolean()),
            ),
            permission_rows,
        )

    company_ids = [
        row[0] for row in bind.execute(sa.text("SELECT id FROM companies")).all()
    ]
    role_ids = {}
    role_rows = []
    for company_id in company_ids:
        for role_code, role_name, description in SYSTEM_ROLES:
            role_id = uuid.uuid4()
            role_ids[(str(company_id), role_code)] = role_id
            role_rows.append({
                "id": role_id,
                "company_id": company_id,
                "code": role_code,
                "name": role_name,
                "description": description,
                "is_system": True,
                "is_active": True,
            })
    if role_rows:
        op.bulk_insert(
            sa.table(
                "company_roles",
                sa.column("id", sa.Uuid()),
                sa.column("company_id", sa.Uuid()),
                sa.column("code", sa.String(40)),
                sa.column("name", sa.String(100)),
                sa.column("description", sa.String(500)),
                sa.column("is_system", sa.Boolean()),
                sa.column("is_active", sa.Boolean()),
            ),
            role_rows,
        )

    permission_role_rows = []
    for company_id in company_ids:
        for role_code, _role_name, _description in SYSTEM_ROLES:
            role_id = role_ids[(str(company_id), role_code)]
            for resource_code, _resource_name in RESOURCES:
                for action_code, _action_name in ACTIONS:
                    allowed = role_code == "OWNER" or (
                        role_code == "MANAGER" and action_code == "view"
                    )
                    permission_role_rows.append({
                        "id": uuid.uuid4(),
                        "role_id": role_id,
                        "permission_id": permission_ids[f"{resource_code}.{action_code}"],
                        "is_allowed": allowed,
                        "data_scope": "ALL" if role_code != "STAFF" else "OWN",
                    })
    if permission_role_rows:
        op.bulk_insert(
            sa.table(
                "company_role_permissions",
                sa.column("id", sa.Uuid()),
                sa.column("role_id", sa.Uuid()),
                sa.column("permission_id", sa.Uuid()),
                sa.column("is_allowed", sa.Boolean()),
                sa.column("data_scope", sa.String(10)),
            ),
            permission_role_rows,
        )

    membership_rows = bind.execute(
        sa.text("SELECT id, company_id, role FROM company_memberships")
    ).all()
    membership_role_rows = []
    for membership_id, company_id, role_code in membership_rows:
        role_id = role_ids.get((str(company_id), role_code))
        if role_id is not None:
            membership_role_rows.append({
                "id": uuid.uuid4(),
                "membership_id": membership_id,
                "role_id": role_id,
                "assigned_by_user_id": None,
            })
    if membership_role_rows:
        op.bulk_insert(
            sa.table(
                "company_membership_roles",
                sa.column("id", sa.Uuid()),
                sa.column("membership_id", sa.Uuid()),
                sa.column("role_id", sa.Uuid()),
                sa.column("assigned_by_user_id", sa.Uuid()),
            ),
            membership_role_rows,
        )


def downgrade() -> None:
    op.drop_index("ix_company_membership_roles_role_id", table_name="company_membership_roles")
    op.drop_table("company_membership_roles")
    op.drop_index("ix_company_role_permissions_role_allowed", table_name="company_role_permissions")
    op.drop_table("company_role_permissions")
    op.drop_index("ix_company_roles_company_active", table_name="company_roles")
    op.drop_table("company_roles")
    op.drop_index("ix_permissions_resource_action", table_name="permissions")
    op.drop_table("permissions")
