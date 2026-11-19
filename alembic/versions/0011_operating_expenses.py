"""Add operating expenses and daily closing expense totals.
Revision ID: 0011_operating_expenses
Revises: 0010_supplier_payables
Create Date: 2026-11-19
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa
revision: str = "0011_operating_expenses"
down_revision: Union[str,None] = "0010_supplier_payables"
branch_labels: Union[str,Sequence[str],None] = None
depends_on: Union[str,Sequence[str],None] = None

def upgrade() -> None:
    op.create_table("operating_expenses",
        sa.Column("id",sa.Uuid(),nullable=False),
        sa.Column("company_id",sa.Uuid(),nullable=False),
        sa.Column("site_id",sa.Uuid(),nullable=False),
        sa.Column("expense_no",sa.String(50),nullable=False),
        sa.Column("expense_date",sa.Date(),nullable=False),
        sa.Column("category_code",sa.String(20),nullable=False),
        sa.Column("description",sa.String(200),nullable=False),
        sa.Column("payee",sa.String(120),nullable=True),
        sa.Column("amount",sa.Numeric(18,2),nullable=False),
        sa.Column("currency_code",sa.String(3),server_default="TWD",nullable=False),
        sa.Column("status",sa.String(10),server_default="UNPAID",nullable=False),
        sa.Column("payment_method",sa.String(12),nullable=True),
        sa.Column("paid_at",sa.DateTime(timezone=True),nullable=True),
        sa.Column("receipt_no",sa.String(100),nullable=True),
        sa.Column("note",sa.String(500),nullable=True),
        sa.Column("created_at",sa.DateTime(timezone=True),server_default=sa.func.now(),nullable=False),
        sa.CheckConstraint("amount > 0",name="ck_operating_expenses_amount_positive"),
        sa.CheckConstraint("currency_code = 'TWD'",name="ck_operating_expenses_currency_twd"),
        sa.CheckConstraint("category_code IN ('RENT','UTILITIES','SALARIES','SUPPLIES','SHIPPING','REPAIR','OTHER')",name="ck_operating_expenses_category"),
        sa.CheckConstraint("status IN ('UNPAID','PAID','VOID')",name="ck_operating_expenses_status"),
        sa.CheckConstraint("payment_method IS NULL OR payment_method IN ('CASH','CARD','TRANSFER','OTHER')",name="ck_operating_expenses_method"),
        sa.CheckConstraint("(status = 'PAID' AND payment_method IS NOT NULL AND paid_at IS NOT NULL) OR (status != 'PAID' AND paid_at IS NULL)",name="ck_operating_expenses_paid_fields"),
        sa.ForeignKeyConstraint(["company_id"],["companies.id"],ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["site_id"],["sites.id"],ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("site_id","expense_no",name="uq_operating_expenses_site_expense_no"))
    op.create_index("ix_operating_expenses_company_site_date","operating_expenses",["company_id","site_id","expense_date"])
    op.create_index("ix_operating_expenses_company_site_paid_at","operating_expenses",["company_id","site_id","paid_at"])
    op.add_column("daily_closings",sa.Column("expenses_paid_amount",sa.Numeric(18,2),server_default="0",nullable=False))
    op.add_column("daily_closing_payment_summaries",sa.Column("expenses_paid_amount",sa.Numeric(18,2),server_default="0",nullable=False))

def downgrade() -> None:
    op.drop_column("daily_closing_payment_summaries","expenses_paid_amount")
    op.drop_column("daily_closings","expenses_paid_amount")
    op.drop_index("ix_operating_expenses_company_site_paid_at",table_name="operating_expenses")
    op.drop_index("ix_operating_expenses_company_site_date",table_name="operating_expenses")
    op.drop_table("operating_expenses")
