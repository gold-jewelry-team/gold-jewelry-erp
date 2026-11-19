"""Company-specific labor fee dark-code configuration."""
import uuid
from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, SmallInteger, String, Uuid, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class LaborCodeSetting(Base):
    __tablename__ = "labor_code_settings"

    company_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("companies.id", ondelete="CASCADE"), primary_key=True
    )
    prefix: Mapped[str] = mapped_column(String(5), nullable=False, default="A", server_default="A")
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )


class LaborCodeMapping(Base):
    __tablename__ = "labor_code_mappings"
    __table_args__ = (
        UniqueConstraint("company_id", "digit", name="uq_labor_code_mappings_company_digit"),
        CheckConstraint("digit >= 0 AND digit <= 9", name="ck_labor_code_mappings_digit_range"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    company_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("companies.id", ondelete="CASCADE"), nullable=False, index=True
    )
    digit: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    code_char: Mapped[str] = mapped_column(String(10), nullable=False)
