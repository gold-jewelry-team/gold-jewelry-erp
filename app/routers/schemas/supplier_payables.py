from datetime import date, datetime
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class SupplierBillCreate(BaseModel):
    site_id: UUID
    supplier_id: UUID
    purchase_id: UUID | None = None
    bill_no: str = Field(min_length=1, max_length=50)
    bill_date: date
    due_date: date | None = None
    currency_code: str = Field(default="TWD", min_length=3, max_length=3, pattern="^[A-Za-z]{3}$")
    total_amount: Decimal = Field(gt=0, max_digits=18, decimal_places=2)
    note: str | None = Field(default=None, max_length=500)


class SupplierBillUpdate(BaseModel):
    bill_no: str | None = Field(default=None, min_length=1, max_length=50)
    bill_date: date | None = None
    due_date: date | None = None
    currency_code: str | None = Field(default=None, min_length=3, max_length=3, pattern="^[A-Za-z]{3}$")
    total_amount: Decimal | None = Field(default=None, gt=0, max_digits=18, decimal_places=2)
    note: str | None = Field(default=None, max_length=500)


class SupplierBillRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    company_id: UUID
    site_id: UUID
    supplier_id: UUID
    purchase_id: UUID | None
    bill_no: str
    bill_date: date
    due_date: date | None
    currency_code: str
    total_amount: Decimal
    paid_amount: Decimal
    outstanding_amount: Decimal
    status: str
    note: str | None
    created_at: datetime
    updated_at: datetime


class SupplierPaymentAllocationCreate(BaseModel):
    bill_id: UUID
    amount: Decimal = Field(gt=0, max_digits=18, decimal_places=2)


class SupplierPaymentCreate(BaseModel):
    site_id: UUID
    supplier_id: UUID
    payment_no: str = Field(min_length=1, max_length=50)
    payment_method: str = Field(pattern="^(CASH|CARD|TRANSFER|OTHER)$")
    allocations: list[SupplierPaymentAllocationCreate] = Field(min_length=1, max_length=100)
    reference_no: str | None = Field(default=None, max_length=100)
    note: str | None = Field(default=None, max_length=500)


class SupplierPaymentAllocationRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    payment_id: UUID
    bill_id: UUID
    amount: Decimal
    reversed_amount: Decimal
    reversible_amount: Decimal
    created_at: datetime


class SupplierPaymentRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    company_id: UUID
    site_id: UUID
    supplier_id: UUID
    payment_no: str
    payment_method: str
    total_amount: Decimal
    currency_code: str
    reference_no: str | None
    paid_at: datetime
    note: str | None
    created_at: datetime
    allocations: list[SupplierPaymentAllocationRead]
    reversed_amount: Decimal
    reversible_amount: Decimal
    status: str


class SupplierPaymentReversalAllocationCreate(BaseModel):
    payment_allocation_id: UUID
    amount: Decimal = Field(gt=0, max_digits=18, decimal_places=2)


class SupplierPaymentReversalCreate(BaseModel):
    reversal_no: str = Field(min_length=1, max_length=50)
    allocations: list[SupplierPaymentReversalAllocationCreate] = Field(min_length=1, max_length=100)
    reason: str = Field(min_length=1, max_length=500)


class SupplierPaymentReversalAllocationRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    reversal_id: UUID
    payment_allocation_id: UUID
    amount: Decimal
    created_at: datetime


class SupplierPaymentReversalRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    company_id: UUID
    site_id: UUID
    supplier_id: UUID
    payment_id: UUID
    reversal_no: str
    total_amount: Decimal
    currency_code: str
    reversed_at: datetime
    reason: str
    created_at: datetime
    allocations: list[SupplierPaymentReversalAllocationRead]
