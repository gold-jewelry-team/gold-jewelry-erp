"""Allow mixed card/cash tender in daily closing payment summaries.

Revision ID: 0019_daily_closing_mixed_payment
Revises: 0018_recon_scope_constraints
Create Date: 2026-11-19
"""
from typing import Sequence, Union

from alembic import op

revision: str = "0019_daily_closing_mixed_payment"
down_revision: Union[str, None] = "0018_recon_scope_constraints"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.drop_constraint(
        "ck_daily_closing_payment_method",
        "daily_closing_payment_summaries",
        type_="check",
    )
    op.create_check_constraint(
        "ck_daily_closing_payment_method",
        "daily_closing_payment_summaries",
        "payment_method IN ('CASH', 'CARD', 'MIXED', 'TRANSFER', 'OTHER')",
    )


def downgrade() -> None:
    op.drop_constraint(
        "ck_daily_closing_payment_method",
        "daily_closing_payment_summaries",
        type_="check",
    )
    op.create_check_constraint(
        "ck_daily_closing_payment_method",
        "daily_closing_payment_summaries",
        "payment_method IN ('CASH', 'CARD', 'TRANSFER', 'OTHER')",
    )
