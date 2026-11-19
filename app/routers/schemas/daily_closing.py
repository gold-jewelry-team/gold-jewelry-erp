from datetime import date, datetime
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class DailyClosingCreate(BaseModel):
    business_date: date
    note: str | None = Field(default=None, max_length=500)


class DailyClosingPaymentSummaryRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    closing_id: UUID
    payment_method: str
    sales_count: int
    returns_count: int
    gross_sales_amount: Decimal
    return_reversal_amount: Decimal
    net_sales_amount: Decimal
    collected_amount: Decimal
    refunded_amount: Decimal
    supplier_paid_amount: Decimal
    expenses_paid_amount: Decimal
    net_cash_flow: Decimal


class DailyClosingRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    company_id: UUID
    site_id: UUID
    business_date: date
    currency_code: str
    sales_count: int
    returns_count: int
    gross_sales_amount: Decimal
    return_reversal_amount: Decimal
    net_sales_amount: Decimal
    collected_amount: Decimal
    refunded_amount: Decimal
    supplier_paid_amount: Decimal
    net_cash_flow: Decimal
    closed_at: datetime
    note: str | None
    payment_summaries: list[DailyClosingPaymentSummaryRead]
