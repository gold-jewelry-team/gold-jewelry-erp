from datetime import datetime
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, computed_field, model_validator

from app.services.pricing.rounding import round_twd_like_legacy


class SaleLineCreate(BaseModel):
    # Catalog items require product/location IDs; temporary estimates carry immutable snapshots only.
    product_id: UUID | None = None
    source_location_id: UUID | None = None
    product_code: str | None = Field(default=None, max_length=50)
    barcode: str | None = Field(default=None, max_length=100)
    product_name: str | None = Field(default=None, min_length=1, max_length=200)
    net_weight: Decimal | None = Field(default=None, gt=0, max_digits=18, decimal_places=4)
    weight_unit_code: str | None = Field(default=None, pattern="^(QIAN|GRAM|TAEL)$")
    labor_fee: Decimal | None = Field(default=None, ge=0, max_digits=18, decimal_places=2)
    old_gold_weight: Decimal = Field(default=Decimal("0"), ge=0, max_digits=18, decimal_places=4)
    trade_in_source: str | None = Field(default=None, pattern="^(LOCAL|EXTERNAL)$")
    trade_in_ratio: Decimal = Field(default=Decimal("0.95"), gt=0, le=1, max_digits=8, decimal_places=6)

    @model_validator(mode="after")
    def validate_catalog_or_estimate(self):
        if self.product_id is None:
            if self.source_location_id is not None:
                raise ValueError("臨時估價商品不可指定庫存出貨位置。")
            if not self.product_name or self.net_weight is None or not self.weight_unit_code:
                raise ValueError("臨時估價成交需提供商品名稱、重量及重量單位。")
        elif self.source_location_id is None:
            raise ValueError("正式商品成交必須指定出貨儲存位置。")
        if self.old_gold_weight > 0 and self.trade_in_source is None:
            raise ValueError("輸入舊金折抵重量時，必須指定本店或外店來源。")
        if self.old_gold_weight == 0 and self.trade_in_source is not None:
            raise ValueError("沒有舊金折抵重量時，不可指定折抵來源。")
        return self


class SaleCreate(BaseModel):
    site_id: UUID
    sale_no: str = Field(min_length=1, max_length=40)
    payment_method: str = Field(default="CASH", pattern="^(CASH|CARD|MIXED|TRANSFER|OTHER)$")
    card_amount: Decimal | None = Field(default=None, ge=0, max_digits=18, decimal_places=2)
    note: str | None = Field(default=None, max_length=500)
    lines: list[SaleLineCreate] = Field(min_length=1, max_length=100)

    @model_validator(mode="after")
    def validate_card_amount(self):
        if self.card_amount is not None and self.payment_method in {"TRANSFER", "OTHER"} and self.card_amount > 0:
            raise ValueError("轉帳或其他付款方式不可同時指定刷卡金額。")
        return self


class SaleLineRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    sale_id: UUID
    line_no: int
    product_id: UUID | None
    source_location_id: UUID | None
    product_code_snapshot: str | None
    barcode_snapshot: str | None
    product_name_snapshot: str
    gross_weight: Decimal
    net_weight: Decimal
    weight_unit_code: str
    labor_fee: Decimal
    sell_gold_price_id: UUID | None
    sell_gold_price_value: Decimal
    sell_gold_price_unit_code: str
    buy_gold_price_id: UUID | None
    buy_gold_price_value: Decimal
    buy_gold_price_unit_code: str
    price_currency_code: str
    price_effective_at: datetime | None
    trade_in_source: str | None
    old_gold_weight: Decimal
    trade_in_ratio: Decimal | None
    adjusted_old_gold_weight: Decimal
    pricing_rule_version: str
    subtotal: Decimal
    card_fee: Decimal
    final_amount: Decimal
    created_at: datetime


class SaleRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    company_id: UUID
    site_id: UUID
    sale_no: str
    status: str
    payment_method: str
    currency_code: str
    subtotal: Decimal
    card_amount: Decimal
    card_fee: Decimal
    final_amount: Decimal
    completed_at: datetime | None
    voided_at: datetime | None
    note: str | None
    created_at: datetime
    updated_at: datetime
    lines: list[SaleLineRead]

    @computed_field
    @property
    def cash_amount(self) -> Decimal:
        """Cash principal only; card fees are displayed separately."""
        if self.payment_method not in {"CASH", "MIXED"}:
            return Decimal("0.00")
        cash = round_twd_like_legacy(self.subtotal) - self.card_amount
        return cash if cash > 0 else Decimal("0.00")


class SaleActionResult(BaseModel):
    sale_id: UUID
    status: str
    message: str
