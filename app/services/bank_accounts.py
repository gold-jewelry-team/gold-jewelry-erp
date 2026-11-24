"""Bank account operations with atomic paired cash-drawer records."""
from datetime import datetime, timezone
from decimal import Decimal
from uuid import UUID, uuid4
from sqlalchemy import select, func
from sqlalchemy.orm import Session
from app.models.bank_account import BankAccount, BankTransaction
from app.models.payment_transaction import PaymentTransaction
from app.models.supplier_payable import SupplierPayment
from app.models.operating_expense import OperatingExpense
from app.models.sale import Sale
from app.models.sale_return import SaleReturn
from app.models.customer_order import CustomerOrder
from app.models.cash_drawer_movement import CashDrawerMovement
from app.models.site import Site
from app.services.daily_closing import assert_business_day_open

def _amount(value: Decimal) -> Decimal:
    if not isinstance(value, Decimal) or value <= 0 or value.quantize(Decimal("0.01")) != value:
        raise ValueError("金額必須是大於零且最多兩位小數。")
    return value

def _actor_text(value: str, field: str) -> str:
    value=value.strip()
    if not value: raise ValueError(f"{field}不可空白。")
    return value

def _account(session: Session, company_id: UUID, account_id: UUID, *, lock: bool=True) -> BankAccount:
    stmt=select(BankAccount).where(BankAccount.id==account_id,BankAccount.company_id==company_id)
    if lock: stmt=stmt.with_for_update()
    account=session.execute(stmt).scalar_one_or_none()
    if account is None: raise ValueError("銀行帳戶不存在或不屬於指定公司。")
    if not account.is_active: raise ValueError("銀行帳戶已停用。")
    return account

def get_bank_account_balance(session: Session, account: BankAccount) -> Decimal:
    incoming=session.scalar(select(func.coalesce(func.sum(BankTransaction.amount),0)).where(
        BankTransaction.bank_account_id==account.id,BankTransaction.direction=="IN"))
    outgoing=session.scalar(select(func.coalesce(func.sum(BankTransaction.amount),0)).where(
        BankTransaction.bank_account_id==account.id,BankTransaction.direction=="OUT"))
    return account.opening_balance + Decimal(incoming) - Decimal(outgoing)

def create_bank_account(session: Session, *, company_id: UUID, bank_name: str, account_name: str,
                        account_last4: str, opening_balance: Decimal, opening_balance_at: datetime) -> BankAccount:
    if not isinstance(opening_balance,Decimal) or opening_balance<0 or opening_balance.quantize(Decimal("0.01"))!=opening_balance:
        raise ValueError("期初餘額不可為負數，且最多兩位小數。")
    last4=account_last4.strip()
    if len(last4)!=4 or not last4.isdigit(): raise ValueError("帳號末四碼必須為四位數字。")
    row=BankAccount(company_id=company_id,bank_name=_actor_text(bank_name,"銀行名稱"),
        account_name=_actor_text(account_name,"帳戶名稱"),account_last4=last4,
        currency_code="TWD",opening_balance=opening_balance,opening_balance_at=opening_balance_at)
    session.add(row); session.flush()
    return row

def _site_for_operation(session: Session, company_id: UUID, site_id: UUID, at: datetime) -> Site:
    site=session.execute(select(Site).where(Site.id==site_id).with_for_update()).scalar_one_or_none()
    if site is None or site.company_id!=company_id: raise ValueError("據點不存在或不屬於指定公司。")
    if not site.is_active: raise ValueError("據點已停用。")
    assert_business_day_open(session,site_id=site_id,at=at)
    return site

def _transaction(session: Session, *, account: BankAccount, site_id: UUID, tx_type: str,
                 direction: str, amount: Decimal, description: str, actor: str,
                 reference_no: str|None, note: str|None, transfer_group_id: UUID|None=None,
                 occurred_at: datetime) -> BankTransaction:
    row=BankTransaction(company_id=account.company_id,bank_account_id=account.id,site_id=site_id,
        transfer_group_id=transfer_group_id,transaction_type=tx_type,direction=direction,
        amount=amount,currency_code="TWD",description=description,created_by_name=actor,
        reference_no=reference_no,note=note,occurred_at=occurred_at)
    session.add(row); session.flush()
    return row

def _cash_movement(session: Session, *, company_id: UUID, site_id: UUID, bank_tx: BankTransaction,
                   movement_type: str, direction: str, amount: Decimal, description: str,
                   actor: str, reference_no: str|None, note: str|None, occurred_at: datetime) -> CashDrawerMovement:
    row=CashDrawerMovement(company_id=company_id,site_id=site_id,movement_type=movement_type,
        direction=direction,amount=amount,currency_code="TWD",reference_no=reference_no,
        description=description,created_by_name=actor,created_at=occurred_at,
        note=note,bank_transaction_id=bank_tx.id)
    session.add(row); session.flush()
    return row

def record_cash_deposit(session: Session, *, company_id: UUID, site_id: UUID, bank_account_id: UUID,
                        amount: Decimal, created_by_name: str, reference_no: str|None=None,
                        note: str|None=None) -> BankTransaction:
    amount=_amount(amount); actor=_actor_text(created_by_name,"經手人")
    description="現金存入銀行"; now=datetime.now(timezone.utc)
    _site_for_operation(session,company_id,site_id,now)
    account=_account(session,company_id,bank_account_id)
    tx=_transaction(session,account=account,site_id=site_id,tx_type="CASH_DEPOSIT",direction="IN",
        amount=amount,description=description,actor=actor,reference_no=reference_no,note=note,occurred_at=now)
    _cash_movement(session,company_id=company_id,site_id=site_id,bank_tx=tx,movement_type="BANK_DEPOSIT",
        direction="OUT",amount=amount,description=description,actor=actor,reference_no=reference_no,note=note,occurred_at=now)
    return tx

def record_cash_withdrawal(session: Session, *, company_id: UUID, site_id: UUID, bank_account_id: UUID,
                           amount: Decimal, created_by_name: str, reference_no: str|None=None,
                           note: str|None=None) -> BankTransaction:
    amount=_amount(amount); actor=_actor_text(created_by_name,"經手人")
    description="銀行提款補充現金櫃"; now=datetime.now(timezone.utc)
    _site_for_operation(session,company_id,site_id,now)
    account=_account(session,company_id,bank_account_id)
    if get_bank_account_balance(session,account)<amount: raise ValueError("銀行帳戶餘額不足，無法提款。")
    tx=_transaction(session,account=account,site_id=site_id,tx_type="CASH_WITHDRAWAL",direction="OUT",
        amount=amount,description=description,actor=actor,reference_no=reference_no,note=note,occurred_at=now)
    _cash_movement(session,company_id=company_id,site_id=site_id,bank_tx=tx,movement_type="BANK_WITHDRAWAL",
        direction="IN",amount=amount,description=description,actor=actor,reference_no=reference_no,note=note,occurred_at=now)
    return tx

def transfer_between_bank_accounts(session: Session, *, company_id: UUID, from_account_id: UUID,
                                   to_account_id: UUID, amount: Decimal, created_by_name: str,
                                   reference_no: str|None=None, note: str|None=None) -> tuple[BankTransaction,BankTransaction]:
    amount=_amount(amount); actor=_actor_text(created_by_name,"經手人")
    if from_account_id==to_account_id: raise ValueError("轉出與轉入不可為同一銀行帳戶。")
    ids=sorted([from_account_id,to_account_id],key=str)
    locked={i:_account(session,company_id,i) for i in ids}
    source,destination=locked[from_account_id],locked[to_account_id]
    if source.currency_code!=destination.currency_code: raise ValueError("不同幣別帳戶不可直接互轉。")
    if get_bank_account_balance(session,source)<amount: raise ValueError("轉出帳戶餘額不足。")
    now=datetime.now(timezone.utc); group=uuid4()
    out_tx=_transaction(session,account=source,site_id=None,tx_type="TRANSFER_OUT",direction="OUT",
        amount=amount,description=f"轉帳至 {destination.bank_name} {destination.account_last4}",
        actor=actor,reference_no=reference_no,note=note,transfer_group_id=group,occurred_at=now)
    in_tx=_transaction(session,account=destination,site_id=None,tx_type="TRANSFER_IN",direction="IN",
        amount=amount,description=f"由 {source.bank_name} {source.account_last4} 轉入",
        actor=actor,reference_no=reference_no,note=note,transfer_group_id=group,occurred_at=now)
    return out_tx,in_tx

class BankTransferLinkConflict(ValueError):
    """Raised when an existing transfer payment is linked elsewhere."""


def _utc_datetime(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _validate_source_site(session: Session, *, company_id: UUID, site_id: UUID) -> None:
    site = session.scalar(
        select(Site).where(Site.id == site_id, Site.company_id == company_id)
    )
    if site is None:
        raise ValueError("轉帳來源據點不存在或不屬於指定公司。")


def _transfer_source_details(
    session: Session,
    *,
    company_id: UUID,
    source_type: str,
    source_id: UUID,
    lock: bool = False,
) -> dict:
    if source_type == "PAYMENT_TRANSACTION":
        statement = select(PaymentTransaction).where(
            PaymentTransaction.id == source_id,
            PaymentTransaction.company_id == company_id,
        )
        if lock:
            statement = statement.with_for_update()
        source = session.scalar(statement)
        if source is None:
            raise ValueError("找不到指定收付款紀錄。")
        if source.payment_method != "TRANSFER" or source.currency_code != "TWD":
            raise ValueError("只有新台幣轉帳收付款可以連結銀行流水。")
        if source.direction not in {"IN", "OUT"}:
            raise ValueError("收付款方向不正確，無法連結銀行流水。")
        if source.sale_id:
            document = session.get(Sale, source.sale_id)
            if document is None or document.company_id != company_id or document.site_id != source.site_id:
                raise ValueError("銷售收付款的來源公司或據點不一致。")
            source_no = document.sale_no
            label = "銷售收款" if source.direction == "IN" else "銷售退款"
        elif source.sale_return_id:
            document = session.get(SaleReturn, source.sale_return_id)
            if document is None or document.company_id != company_id or document.site_id != source.site_id:
                raise ValueError("退貨收付款的來源公司或據點不一致。")
            source_no = document.return_no
            label = "退貨收款" if source.direction == "IN" else "退貨退款"
        elif source.customer_order_id:
            document = session.get(CustomerOrder, source.customer_order_id)
            if document is None or document.company_id != company_id or document.site_id != source.site_id:
                raise ValueError("客訂收付款的來源公司或據點不一致。")
            source_no = document.order_no
            label = "客訂收款" if source.direction == "IN" else "客訂退款"
        else:
            raise ValueError("收付款來源不完整，無法連結銀行流水。")
        return {
            "source": source,
            "site_id": source.site_id,
            "direction": source.direction,
            "amount": source.amount,
            "currency_code": source.currency_code,
            "reference_no": source.reference_no,
            "occurred_at": source.paid_at,
            "note": source.note,
            "source_no": source_no,
            "description": f"{label}：{source_no}",
        }

    if source_type == "SUPPLIER_PAYMENT":
        statement = select(SupplierPayment).where(
            SupplierPayment.id == source_id,
            SupplierPayment.company_id == company_id,
        )
        if lock:
            statement = statement.with_for_update()
        source = session.scalar(statement)
        if source is None:
            raise ValueError("找不到指定供應商付款紀錄。")
        if source.payment_method != "TRANSFER" or source.currency_code != "TWD":
            raise ValueError("只有新台幣轉帳付款可以連結銀行流水。")
        _validate_source_site(session, company_id=company_id, site_id=source.site_id)
        return {
            "source": source,
            "site_id": source.site_id,
            "direction": "OUT",
            "amount": source.total_amount,
            "currency_code": source.currency_code,
            "reference_no": source.reference_no or source.payment_no,
            "occurred_at": source.paid_at,
            "note": source.note,
            "source_no": source.payment_no,
            "description": f"供應商轉帳付款：{source.payment_no}",
        }

    if source_type == "OPERATING_EXPENSE":
        statement = select(OperatingExpense).where(
            OperatingExpense.id == source_id,
            OperatingExpense.company_id == company_id,
        )
        if lock:
            statement = statement.with_for_update()
        source = session.scalar(statement)
        if source is None:
            raise ValueError("找不到指定營業費用紀錄。")
        if source.status != "PAID" or source.payment_method != "TRANSFER" or source.currency_code != "TWD":
            raise ValueError("只有已付款的新台幣轉帳費用可以連結銀行流水。")
        if source.paid_at is None:
            raise ValueError("費用付款時間不存在，無法連結銀行流水。")
        _validate_source_site(session, company_id=company_id, site_id=source.site_id)
        return {
            "source": source,
            "site_id": source.site_id,
            "direction": "OUT",
            "amount": source.amount,
            "currency_code": source.currency_code,
            "reference_no": source.receipt_no or source.expense_no,
            "occurred_at": source.paid_at,
            "note": source.note,
            "source_no": source.expense_no,
            "description": f"營業費用轉帳：{source.expense_no} · {source.description}",
        }

    raise ValueError("不支援的轉帳來源類型。")


def list_unlinked_transfer_sources(
    session: Session, *, company_id: UUID, limit: int = 200
) -> list[dict]:
    linked = {
        (row.source_type, row.source_id)
        for row in session.scalars(
            select(BankTransaction).where(
                BankTransaction.company_id == company_id,
                BankTransaction.source_type.is_not(None),
                BankTransaction.source_id.is_not(None),
            )
        ).all()
    }
    candidates: list[tuple[datetime, str, UUID]] = []
    payment_rows = session.scalars(
        select(PaymentTransaction).where(
            PaymentTransaction.company_id == company_id,
            PaymentTransaction.payment_method == "TRANSFER",
            PaymentTransaction.currency_code == "TWD",
        ).order_by(PaymentTransaction.paid_at.desc()).limit(limit)
    ).all()
    candidates.extend(
        (row.paid_at, "PAYMENT_TRANSACTION", row.id)
        for row in payment_rows
        if ("PAYMENT_TRANSACTION", row.id) not in linked
    )
    supplier_rows = session.scalars(
        select(SupplierPayment).where(
            SupplierPayment.company_id == company_id,
            SupplierPayment.payment_method == "TRANSFER",
            SupplierPayment.currency_code == "TWD",
        ).order_by(SupplierPayment.paid_at.desc()).limit(limit)
    ).all()
    candidates.extend(
        (row.paid_at, "SUPPLIER_PAYMENT", row.id)
        for row in supplier_rows
        if ("SUPPLIER_PAYMENT", row.id) not in linked
    )
    expense_rows = session.scalars(
        select(OperatingExpense).where(
            OperatingExpense.company_id == company_id,
            OperatingExpense.status == "PAID",
            OperatingExpense.payment_method == "TRANSFER",
            OperatingExpense.currency_code == "TWD",
            OperatingExpense.paid_at.is_not(None),
        ).order_by(OperatingExpense.paid_at.desc()).limit(limit)
    ).all()
    candidates.extend(
        (row.paid_at, "OPERATING_EXPENSE", row.id)
        for row in expense_rows
        if ("OPERATING_EXPENSE", row.id) not in linked
    )
    candidates.sort(key=lambda item: _utc_datetime(item[0]), reverse=True)
    output = []
    for occurred_at, source_type, source_id in candidates[:limit]:
        details = _transfer_source_details(
            session,
            company_id=company_id,
            source_type=source_type,
            source_id=source_id,
        )
        output.append({
            "source_type": source_type,
            "source_id": source_id,
            "site_id": details["site_id"],
            "source_no": details["source_no"],
            "description": details["description"],
            "direction": details["direction"],
            "amount": details["amount"],
            "currency_code": details["currency_code"],
            "reference_no": details["reference_no"],
            "occurred_at": details["occurred_at"],
            "note": details["note"],
        })
    return output


def link_transfer_source_to_bank_account(
    session: Session,
    *,
    company_id: UUID,
    bank_account_id: UUID,
    source_type: str,
    source_id: UUID,
    created_by_name: str,
) -> tuple[BankTransaction, bool]:
    actor = _actor_text(created_by_name, "連結經手人")
    account = _account(session, company_id, bank_account_id)
    existing = session.scalar(
        select(BankTransaction).where(
            BankTransaction.company_id == company_id,
            BankTransaction.source_type == source_type,
            BankTransaction.source_id == source_id,
        ).with_for_update()
    )
    if existing is not None:
        if existing.bank_account_id != account.id:
            raise BankTransferLinkConflict("此筆轉帳已連結到另一個銀行帳戶，不可重複連結。")
        return existing, False

    details = _transfer_source_details(
        session,
        company_id=company_id,
        source_type=source_type,
        source_id=source_id,
        lock=True,
    )
    occurred_at = _utc_datetime(details["occurred_at"])
    if occurred_at < _utc_datetime(account.opening_balance_at):
        raise ValueError(
            "這筆轉帳早於所選銀行帳戶的期初餘額日期；可能已包含在期初餘額中，為避免重複計入請勿連結。"
        )
    transaction_type = "TRANSFER_IN" if details["direction"] == "IN" else "TRANSFER_OUT"
    description = details["description"][:200]
    row = BankTransaction(
        company_id=company_id,
        bank_account_id=account.id,
        site_id=details["site_id"],
        transaction_type=transaction_type,
        direction=details["direction"],
        amount=details["amount"],
        currency_code=details["currency_code"],
        reference_no=details["reference_no"],
        description=description,
        created_by_name=actor,
        occurred_at=occurred_at,
        note=details["note"],
        source_type=source_type,
        source_id=source_id,
    )
    session.add(row)
    session.flush()
    return row, True

