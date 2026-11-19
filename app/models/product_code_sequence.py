import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, Uuid, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class ProductCodeSequence(Base):
    """One shared numeric sequence per company, regardless of product prefix."""
    __tablename__ = "product_code_sequences"

    company_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("companies.id", ondelete="CASCADE"),
        primary_key=True,
    )
    next_number: Mapped[int] = mapped_column(Integer, nullable=False, default=1, server_default="1")
    number_width: Mapped[int] = mapped_column(Integer, nullable=False, default=5, server_default="5")
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )
