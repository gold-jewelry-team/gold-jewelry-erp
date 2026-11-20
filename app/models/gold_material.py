"""Fine-gold material ledger and supplier settlement allocations."""
import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, Numeric, String, Uuid, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class GoldMaterialMovement(Base):
    __tablename__ = "gold_material_movements"
    __table_args__ = (
        CheckConstraint(
            "movement_type IN ('OPENING', 'RECEIPT', 'ADJUSTMENT_IN', 'ADJUSTMENT_OUT', 'SUPPLIER_DELIVERY')",
            name="ck_gold_material_movements_type",
        ),
        CheckConstraint("purity_ratio > 0 AND purity_ratio <= 1", name="ck_gold_material_purity_ratio"),
        CheckConstraint("gross_weight > 0 AND loss_weight >= 0 AND net_weight > 0", name="ck_gold_material_weights"),
        CheckConstraint("fine_gold_weight_g > 0", name="ck_gold_material_fine_weight"),
        CheckConstraint("gold_price_value > 0 AND deduction_amount >= 0 AND valuation_amount > 0", name="ck_gold_material_valuation"),
        CheckConstraint("weight_unit_code IN ('G', 'QIAN', 'LIANG')", name="ck_gold_material_weight_unit"),
        CheckConstraint("gold_price_unit_code IN ('G', 'QIAN', 'LIANG')", name="ck_gold_material_price_unit"),
        UniqueConstraint("site_id", "movement_no", name="uq_gold_material_site_movement_no"),
        Index("ix_gold_material_company_site_time", "company_id", "site_id", "occurred_at"),
        Index("ix_gold_material_purchase_id", "purchase_id"),
        Index("ix_gold_material_supplier_id", "supplier_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    company_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), ForeignKey("companies.id", ondelete="RESTRICT"), nullable=False)
    site_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), ForeignKey("sites.id", ondelete="RESTRICT"), nullable=False)
    supplier_id: Mapped[uuid.UUID | None] = mapped_column(Uuid(as_uuid=True), ForeignKey("suppliers.id", ondelete="RESTRICT"), nullable=True)
    purchase_id: Mapped[uuid.UUID | None] = mapped_column(Uuid(as_uuid=True), ForeignKey("purchases.id", ondelete="RESTRICT"), nullable=True)
    movement_no: Mapped[str] = mapped_column(String(50), nullable=False)
    movement_type: Mapped[str] = mapped_column(String(24), nullable=False)
    source_type: Mapped[str | None] = mapped_column(String(30), nullable=True)
    purity_label: Mapped[str] = mapped_column(String(30), nullable=False)
    purity_ratio: Mapped[Decimal] = mapped_column(Numeric(8, 6), nullable=False)
    gross_weight: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False)
    loss_weight: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False, default=Decimal("0"), server_default="0")
    net_weight: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False)
    weight_unit_code: Mapped[str] = mapped_column(String(10), nullable=False)
    fine_gold_weight_g: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False)
    gold_price_value: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    gold_price_unit_code: Mapped[str] = mapped_column(String(10), nullable=False)
    deduction_amount: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False, default=Decimal("0"), server_default="0")
    valuation_amount: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    note: Mapped[str | None] = mapped_column(String(500), nullable=True)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())

    allocations: Mapped[list["GoldMaterialSettlementAllocation"]] = relationship(
        back_populates="movement", order_by="GoldMaterialSettlementAllocation.created_at"
    )


class GoldMaterialSettlementAllocation(Base):
    __tablename__ = "gold_material_settlement_allocations"
    __table_args__ = (
        CheckConstraint("amount > 0", name="ck_gold_material_settlement_amount_positive"),
        UniqueConstraint("movement_id", "bill_id", name="uq_gold_material_settlement_movement_bill"),
        Index("ix_gold_material_settlement_bill_id", "bill_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    movement_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), ForeignKey("gold_material_movements.id", ondelete="RESTRICT"), nullable=False)
    bill_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), ForeignKey("supplier_bills.id", ondelete="RESTRICT"), nullable=False)
    amount: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())

    movement: Mapped["GoldMaterialMovement"] = relationship(back_populates="allocations")
    bill: Mapped["SupplierBill"] = relationship(back_populates="gold_allocations")
