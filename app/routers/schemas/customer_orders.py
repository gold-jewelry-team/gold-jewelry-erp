from datetime import datetime
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, computed_field, model_validator


class CustomerOrderPaymentCreate(BaseModel):
    amount: Decimal = Field(gt=0, max_digits=18, decimal_places=2)
    payment_method: str = Field(default="CASH", pattern="^(CASH|CARD|TRANSFER|OTHER)$")
    note: str | None = Field(default=None, max_length=500)
    idempotency_key: UUID | None = None


class CustomerOrderCreate(BaseModel):
    site_id: UUID
    order_no: str = Field(min_length=1, max_length=40)
    customer_name: str = Field(min_length=1, max_length=120)
    customer_phone: str | None = Field(default=None, max_length=40)
    expected_delivery_date: datetime | None = None
    items: list[dict] = Field(min_length=1, max_length=100)
    total_amount: Decimal = Field(gt=0, max_digits=18, decimal_places=2)
    initial_deposit: Decimal = Field(gt=0, max_digits=18, decimal_places=2)
    payment_method: str = Field(default="CASH", pattern="^(CASH|CARD|TRANSFER|OTHER)$")
    note: str | None = Field(default=None, max_length=1000)
    idempotency_key: UUID | None = None

    @model_validator(mode="after")
    def validate_deposit(self):
        if self.initial_deposit > self.total_amount:
            raise ValueError("訂金不可超過訂購總額。")
        return self


class CustomerOrderPaymentRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    customer_order_id: UUID
    direction: str
    amount: Decimal
    payment_method: str
    note: str | None
    paid_at: datetime


class CustomerOrderUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    order_no: str | None = Field(default=None, min_length=1, max_length=40)
    customer_name: str | None = Field(default=None, min_length=1, max_length=120)
    customer_phone: str | None = Field(default=None, max_length=40)
    expected_delivery_date: datetime | None = None
    note: str | None = Field(default=None, max_length=1000)


class CustomerOrderRefundCreate(BaseModel):
    amount: Decimal = Field(gt=0, max_digits=18, decimal_places=2)
    payment_method: str = Field(default="CASH", pattern="^(CASH|CARD|TRANSFER|OTHER)$")
    note: str | None = Field(default=None, max_length=500)
    idempotency_key: UUID | None = None


class CustomerOrderRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    company_id: UUID
    site_id: UUID
    order_no: str
    status: str
    customer_name: str
    customer_phone: str | None
    expected_delivery_date: datetime | None
    currency_code: str
    items: list[dict]
    total_amount: Decimal
    final_sale_amount: Decimal | None
    deposit_amount: Decimal
    note: str | None
    created_at: datetime
    updated_at: datetime
    payments: list[CustomerOrderPaymentRead]

    @computed_field
    @property
    def sale_id(self) -> UUID | None:
        return self.sale.id if self.sale is not None else None

    @computed_field
    @property
    def sale_no(self) -> str | None:
        return self.sale.sale_no if self.sale is not None else None

    @computed_field
    @property
    def sale_status(self) -> str | None:
        return self.sale.status if self.sale is not None else None

    @computed_field
    @property
    def balance_amount(self) -> Decimal:
        if self.status == "CANCELLED":
            return Decimal("0.00")
        payable = self.final_sale_amount if self.final_sale_amount is not None else self.total_amount
        return payable - self.deposit_amount
