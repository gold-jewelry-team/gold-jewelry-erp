""""Persist the actual card principal and allow mixed tender sales.

Revision ID: 0008_sales_card_tender
Revises: 0007_sales_returns
Create Date: 2026-11-19
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0008_sales_card_tender"
down_revision: Union[str, None] = "0007_sales_returns"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "sales",
        sa.Column("card_amount", sa.Numeric(18, 2), nullable=False, server_default="0"),
    )

    # Before this migration, CARD meant the entire order was paid by card.
    # Preserve that historical principal instead of leaving legacy card sales
    # with the new column's default value of zero. Use the same positive-TWD
    # half-up rule as the application; negative/zero totals cannot be card
    # principal and are safely recorded as zero.
    sales = sa.table(
        "sales",
        sa.column("payment_method", sa.String(length=12)),
        sa.column("subtotal", sa.Numeric(18, 2)),
        sa.column("card_amount", sa.Numeric(18, 2)),
    )
    op.execute(
        sales.update()
        .where(sales.c.payment_method == "CARD")
        .values(
            card_amount=sa.case(
                (sales.c.subtotal > 0, sa.func.floor(sales.c.subtotal + sa.literal(0.5))),
                else_=sa.literal(0),
            )
        )
    )

    op.drop_constraint("ck_sales_payment_method", "sales", type_="check")
    op.create_check_constraint(
        "ck_sales_payment_method",
        "sales",
        "payment_method IN ('CASH', 'CARD', 'MIXED', 'TRANSFER', 'OTHER')",
    )


def downgrade() -> None:
    op.drop_constraint("ck_sales_payment_method", "sales", type_="check")
    op.create_check_constraint(
        "ck_sales_payment_method",
        "sales",
        "payment_method IN ('CASH', 'CARD', 'TRANSFER', 'OTHER')",
    )
    op.drop_column("sales", "card_amount")
"