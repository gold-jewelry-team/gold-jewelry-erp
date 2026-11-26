"""Supplier bills, supplier disbursements, and bill payment allocations."""
import uuid
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import CheckConstraint, Date, DateTime, ForeignKey, Index, Numeric, String, Uuid, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class SupplierBill(Base):
    __tablename__ = "supplier_bills"
    __table_args__ = (
        CheckConstraint("total_amount > 0", name="ck_supplier_bills_total_positive"),
        CheckConstraint("status IN ('OPEN', 'PARTIALLY_PAID', 'PAID', 'VOID')", name="ck_supplier_bills_status"),
        UniqueConstraint("company_id", "supplier_id", "bill_no", name="uq_supplier_bills_supplier_bill_no"),
        Index("ix_supplier_bills_company_site_due", "company_id", "site_id", "due_date"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    company_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), ForeignKey("companies.id", ondelete="RESTRICT"), nullable=False)
    site_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), ForeignKey("sites.id", ondelete="RESTRICT"), nullable=False)
    supplier_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), ForeignKey("suppliers.id", ondelete="RESTRICT"), nullable=False)
    purchase_id: Mapped[uuid.UUID | None] = mapped_column(Uuid(as_uuid=True), ForeignKey("purchases.id", ondelete="RESTRICT"), nullable=True)
    bill_no: Mapped[str] = mapped_column(String(50), nullable=False)
    bill_date: Mapped[date] = mapped_column(Date, nullable=False)
    due_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    currency_code: Mapped[str] = mapped_column(String(3), nullable=False, default="TWD", server_default="TWD")
    total_amount: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="OPEN", server_default="OPEN")
    note: Mapped[str | None] = mapped_column(String(500), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())
    allocations: Mapped[list["SupplierPaymentAllocation"]] = relationship(
        back_populates="bill", order_by="SupplierPaymentAllocation.created_at"
    )
    gold_allocations: Mapped[list["GoldMaterialSettlementAllocation"]] = relationship(
        back_populates="bill", order_by="GoldMaterialSettlementAllocation.created_at"
    )

    @property
    def paid_amount(self) -> Decimal:
        cash_paid = sum(
            (item.amount - item.reversed_amount for item in self.allocations),
            Decimal("0"),
        )
        gold_paid = sum((item.amount for item in self.gold_allocations), Decimal("0"))
        return cash_paid + gold_paid

    @property
    def outstanding_amount(self) -> Decimal:
        return self.total_amount - self.paid_amount


class SupplierPayment(Base):
    __tablename__ = "supplier_payments"
    __table_args__ = (
        CheckConstraint("total_amount > 0", name="ck_supplier_payments_total_positive"),
        CheckConstraint("payment_method IN ('CASH', 'CARD', 'TRANSFER', 'OTHER')", name="ck_supplier_payments_method"),
        UniqueConstraint("site_id", "payment_no", name="uq_supplier_payments_site_payment_no"),
        Index("ix_supplier_payments_company_site_paid_at", "company_id", "site_id", "paid_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    company_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), ForeignKey("companies.id", ondelete="RESTRICT"), nullable=False)
    site_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), ForeignKey("sites.id", ondelete="RESTRICT"), nullable=False)
    supplier_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), ForeignKey("suppliers.id", ondelete="RESTRICT"), nullable=False)
    payment_no: Mapped[str] = mapped_column(String(50), nullable=False)
    payment_method: Mapped[str] = mapped_column(String(12), nullable=False)
    total_amount: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    currency_code: Mapped[str] = mapped_column(String(3), nullable=False, default="TWD", server_default="TWD")
    reference_no: Mapped[str | None] = mapped_column(String(100), nullable=True)
    paid_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    note: Mapped[str | None] = mapped_column(String(500), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    allocations: Mapped[list["SupplierPaymentAllocation"]] = relationship(
        back_populates="payment", cascade="all, delete-orphan", order_by="SupplierPaymentAllocation.created_at"
    )
    reversals: Mapped[list["SupplierPaymentReversal"]] = relationship(
        back_populates="payment", order_by="SupplierPaymentReversal.reversed_at"
    )

    @property
    def reversed_amount(self) -> Decimal:
        return sum((item.total_amount for item in self.reversals), Decimal("0"))

    @property
    def reversible_amount(self) -> Decimal:
        return max(Decimal("0.00"), self.total_amount - self.reversed_amount)

    @property
    def status(self) -> str:
        if self.reversed_amount == 0:
            return "POSTED"
        if self.reversible_amount == 0:
            return "REVERSED"
        return "PARTIALLY_REVERSED"


class SupplierPaymentAllocation(Base):
    __tablename__ = "supplier_payment_allocations"
    __table_args__ = (
        CheckConstraint("amount > 0", name="ck_supplier_payment_allocations_amount_positive"),
        UniqueConstraint("payment_id", "bill_id", name="uq_supplier_payment_allocation_payment_bill"),
        Index("ix_supplier_payment_allocations_bill_id", "bill_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    payment_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), ForeignKey("supplier_payments.id", ondelete="RESTRICT"), nullable=False)
    bill_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), ForeignKey("supplier_bills.id", ondelete="RESTRICT"), nullable=False)
    amount: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    payment: Mapped["SupplierPayment"] = relationship(back_populates="allocations")
    bill: Mapped["SupplierBill"] = relationship(back_populates="allocations")
    reversal_allocations: Mapped[list["SupplierPaymentReversalAllocation"]] = relationship(
        back_populates="payment_allocation",
        order_by="SupplierPaymentReversalAllocation.created_at",
    )

    @property
    def reversed_amount(self) -> Decimal:
        return sum((item.amount for item in self.reversal_allocations), Decimal("0"))

    @property
    def reversible_amount(self) -> Decimal:
        return max(Decimal("0.00"), self.amount - self.reversed_amount)


class SupplierPaymentReversal(Base):
    """Append-only reversal header for a previously recorded supplier payment."""

    __tablename__ = "supplier_payment_reversals"
    __table_args__ = (
        CheckConstraint("total_amount > 0", name="ck_supplier_payment_reversals_total_positive"),
        UniqueConstraint("site_id", "reversal_no", name="uq_supplier_payment_reversals_site_no"),
        Index("ix_supplier_payment_reversals_company_site_reversed_at", "company_id", "site_id", "reversed_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    company_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), ForeignKey("companies.id", ondelete="RESTRICT"), nullable=False)
    site_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), ForeignKey("sites.id", ondelete="RESTRICT"), nullable=False)
    supplier_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), ForeignKey("suppliers.id", ondelete="RESTRICT"), nullable=False)
    payment_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), ForeignKey("supplier_payments.id", ondelete="RESTRICT"), nullable=False)
    reversal_no: Mapped[str] = mapped_column(String(50), nullable=False)
    total_amount: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    currency_code: Mapped[str] = mapped_column(String(3), nullable=False, default="TWD", server_default="TWD")
    reversed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    reason: Mapped[str] = mapped_column(String(500), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())

    payment: Mapped["SupplierPayment"] = relationship(back_populates="reversals")
    allocations: Mapped[list["SupplierPaymentReversalAllocation"]] = relationship(
        back_populates="reversal",
        order_by="SupplierPaymentReversalAllocation.created_at",
    )


class SupplierPaymentReversalAllocation(Base):
    """Amount reversed from one exact original supplier-payment allocation."""

    __tablename__ = "supplier_payment_reversal_allocations"
    __table_args__ = (
        CheckConstraint("amount > 0", name="ck_supplier_payment_reversal_allocations_amount_positive"),
        UniqueConstraint(
            "reversal_id", "payment_allocation_id",
            name="uq_supplier_payment_reversal_allocation_original",
        ),
        Index("ix_supplier_payment_reversal_allocations_original", "payment_allocation_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    reversal_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), ForeignKey("supplier_payment_reversals.id", ondelete="RESTRICT"), nullable=False)
    payment_allocation_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), ForeignKey("supplier_payment_allocations.id", ondelete="RESTRICT"), nullable=False)
    amount: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())

    reversal: Mapped["SupplierPaymentReversal"] = relationship(back_populates="allocations")
    payment_allocation: Mapped["SupplierPaymentAllocation"] = relationship(back_populates="reversal_allocations")
