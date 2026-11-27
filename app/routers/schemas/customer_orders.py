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


class CustomerOrderSaleLineRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    product_name_snapshot: str
    net_weight: Decimal
    weight_unit_code: str
    final_amount: Decimal


class CustomerOrderSaleReturnPaymentRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    direction: str
    amount: Decimal
    payment_method: str
    paid_at: datetime


class CustomerOrderSaleReturnLineRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    sale_line_id: UUID
    product_name_snapshot: str
    net_weight: Decimal
    weight_unit_code: str
    settlement_reversal_amount: Decimal


class CustomerOrderSaleReturnRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    return_no: str
    settlement_reversal_amount: Decimal
    currency_code: str
    reason: str | None
    note: str | None
    created_at: datetime
    lines: list[CustomerOrderSaleReturnLineRead]
    payments: list[CustomerOrderSaleReturnPaymentRead]

    @computed_field
    @property
    def settlement_direction(self) -> str:
        if self.settlement_reversal_amount < 0:
            return "OUT"
        if self.settlement_reversal_amount > 0:
            return "IN"
        return "NONE"

    @computed_field
    @property
    def settled_amount(self) -> Decimal:
        if self.settlement_direction == "NONE":
            return Decimal("0.00")
        total = sum(
            (payment.amount for payment in self.payments if payment.direction == self.settlement_direction),
            Decimal("0.00"),
        )
        return min(total, abs(self.settlement_reversal_amount))

    @computed_field
    @property
    def outstanding_amount(self) -> Decimal:
        return max(Decimal("0.00"), abs(self.settlement_reversal_amount) - self.settled_amount)

    @computed_field
    @property
    def settlement_status(self) -> str:
        if self.settlement_direction == "NONE":
            return "NO_SETTLEMENT"
        if self.settled_amount == 0:
            return "UNPAID"
        if self.outstanding_amount > 0:
            return "PARTIAL"
        return "SETTLED"


class CustomerOrderSaleRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    sale_no: str
    status: str
    final_amount: Decimal
    currency_code: str
    lines: list[CustomerOrderSaleLineRead]
    returns: list[CustomerOrderSaleReturnRead]

    @computed_field
    @property
    def line_count(self) -> int:
        return len(self.lines)

    @computed_field
    @property
    def returned_line_count(self) -> int:
        return sum(len(returned.lines) for returned in self.returns)

    @computed_field
    @property
    def return_count(self) -> int:
        return len(self.returns)

    @computed_field
    @property
    def return_status(self) -> str:
        if not self.returns:
            return "NONE"
        if self.line_count > 0 and self.returned_line_count >= self.line_count:
            return "FULL"
        return "PARTIAL"

    @computed_field
    @property
    def return_reversal_amount(self) -> Decimal:
        return sum(
            (returned.settlement_reversal_amount for returned in self.returns),
            Decimal("0.00"),
        )


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
    sale: CustomerOrderSaleRead | None = None

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
