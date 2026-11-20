"""Supplier master data."""
import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, String, Uuid, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class Supplier(Base):
    __tablename__ = "suppliers"
    __table_args__ = (
        UniqueConstraint("company_id", "code", name="uq_suppliers_company_code"),
        UniqueConstraint("id", "company_id", name="uq_suppliers_id_company"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    company_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), ForeignKey("companies.id", ondelete="RESTRICT"), nullable=False, index=True)
    code: Mapped[str] = mapped_column(String(40), nullable=False)
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    tax_id: Mapped[str | None] = mapped_column(String(20), nullable=True)
    contact_name: Mapped[str | None] = mapped_column(String(80), nullable=True)
    phone: Mapped[str | None] = mapped_column(String(40), nullable=True)
    address: Mapped[str | None] = mapped_column(String(255), nullable=True)
    note: Mapped[str | None] = mapped_column(String(500), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default="true")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())
