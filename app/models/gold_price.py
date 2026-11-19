import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Numeric,
    String,
    Uuid,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class GoldPrice(Base):
    """An immutable-in-practice snapshot of a buy or sell gold price."""

    __tablename__ = "gold_prices"
    __table_args__ = (
        CheckConstraint("price_type IN ('BUY', 'SELL')", name="ck_gold_prices_price_type"),
        CheckConstraint("price_value > 0", name="ck_gold_prices_price_value_positive"),
        CheckConstraint("length(currency_code) = 3", name="ck_gold_prices_currency_code_length"),
        CheckConstraint("length(unit_code) BETWEEN 1 AND 20", name="ck_gold_prices_unit_code_length"),
        CheckConstraint(
            "source IN ('MANUAL', 'IMPORT', 'SYSTEM')",
            name="ck_gold_prices_source",
        ),
        Index(
            "ix_gold_prices_scope_type_effective",
            "company_id",
            "site_id",
            "price_type",
            "effective_at",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    company_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("companies.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    # NULL means company-wide default; a site-specific row overrides it.
    site_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("sites.id", ondelete="RESTRICT"),
        nullable=True,
        index=True,
    )
    price_type: Mapped[str] = mapped_column(String(10), nullable=False)
    price_value: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False)
    currency_code: Mapped[str] = mapped_column(String(3), nullable=False, default="TWD", server_default="TWD")
    # Unit is explicit and configurable (e.g. TWD_PER_QIAN or TWD_PER_GRAM).
    unit_code: Mapped[str] = mapped_column(String(20), nullable=False)
    effective_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    source: Mapped[str] = mapped_column(String(10), nullable=False, default="MANUAL", server_default="MANUAL")
    note: Mapped[str | None] = mapped_column(String(500), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())

    company: Mapped["Company"] = relationship()
    site: Mapped["Site | None"] = relationship()
