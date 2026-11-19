"""Bank account operations with atomic paired cash-drawer records."""
from datetime import datetime, timezone
from decimal import Decimal
from uuid import UUID, uuid4
from sqlalchemy import select, func
from sqlalchemy.orm import Session
from app.models.bank_account import BankAccount, BankTransaction
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
