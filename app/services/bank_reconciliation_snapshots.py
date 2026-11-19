"""Create immutable bank reconciliation snapshots."""
from datetime import date, datetime, time, timedelta
from decimal import Decimal
from uuid import UUID
from zoneinfo import ZoneInfo
from sqlalchemy import select, func
from sqlalchemy.orm import Session
from app.models.bank_account import BankAccount, BankTransaction
from app.models.bank_statement import BankStatementImport, BankStatementLine
from app.models.bank_reconciliation import BankReconciliationSnapshot

TAIPEI=ZoneInfo("Asia/Taipei")

def create_reconciliation_snapshot(session: Session, *, company_id: UUID, bank_account_id: UUID,
    import_id: UUID, period_start: date, period_end: date,
    statement_opening_balance: Decimal, statement_closing_balance: Decimal,
    reconciled_by_name: str, note: str | None = None) -> BankReconciliationSnapshot:
    if period_end < period_start:
        raise ValueError("對帳期間結束日不可早於開始日。")
    actor=reconciled_by_name.strip()
    if not actor:
        raise ValueError("對帳人不可空白。")
    opening=Decimal(statement_opening_balance)
    closing=Decimal(statement_closing_balance)
    if opening.quantize(Decimal("0.01"))!=opening or closing.quantize(Decimal("0.01"))!=closing:
        raise ValueError("期初及期末餘額最多只能有兩位小數。")
    account=session.execute(select(BankAccount).where(
        BankAccount.id==bank_account_id,BankAccount.company_id==company_id
    ).with_for_update()).scalar_one_or_none()
    if account is None:
        raise ValueError("銀行帳戶不存在或不屬於此公司。")
    batch=session.execute(select(BankStatementImport).where(
        BankStatementImport.id==import_id,
        BankStatementImport.company_id==company_id,
        BankStatementImport.bank_account_id==bank_account_id
    )).scalar_one_or_none()
    if batch is None:
        raise ValueError("對帳單匯入批次不存在或不屬於此銀行帳戶。")
    lines=list(session.scalars(select(BankStatementLine).where(
        BankStatementLine.import_id==import_id,
        BankStatementLine.company_id==company_id,
        BankStatementLine.bank_account_id==bank_account_id,
    ).with_for_update()).all())
    if not lines:
        raise ValueError("指定期間沒有對帳單明細。")
    if any(line.transaction_date<period_start or line.transaction_date>period_end for line in lines):
        raise ValueError("對帳單明細超出指定期間。")
    statement_net=sum((line.amount if line.direction=="IN" else -line.amount
        for line in lines if line.status!="DUPLICATE"),Decimal("0.00"))
    start=datetime.combine(period_start,time.min,tzinfo=TAIPEI).astimezone(ZoneInfo("UTC"))
    end=datetime.combine(period_end+timedelta(days=1),time.min,tzinfo=TAIPEI).astimezone(ZoneInfo("UTC"))
    ledger_rows=list(session.scalars(select(BankTransaction).where(
        BankTransaction.company_id==company_id,
        BankTransaction.bank_account_id==bank_account_id,
        BankTransaction.occurred_at>=start,
        BankTransaction.occurred_at<end
    ).with_for_update()).all())
    ledger_net=sum((tx.amount if tx.direction=="IN" else -tx.amount for tx in ledger_rows),Decimal("0.00"))
    matched_ids={line.matched_bank_transaction_id for line in lines
        if line.status=="MATCHED" and line.matched_bank_transaction_id is not None}
    unmatched_ledger=sum(1 for tx in ledger_rows if tx.id not in matched_ids)
    matched_count=sum(1 for line in lines if line.status=="MATCHED")
    unmatched_count=sum(1 for line in lines if line.status=="UNMATCHED")
    duplicate_count=sum(1 for line in lines if line.status=="DUPLICATE")
    ignored_count=sum(1 for line in lines if line.status=="IGNORED")
    balance_net=closing-opening
    difference=statement_net-ledger_net
    balance_difference=balance_net-statement_net
    status="RECONCILED" if (
        unmatched_count==0 and duplicate_count==0 and unmatched_ledger==0
        and difference==0 and balance_difference==0
    ) else "NEEDS_REVIEW"
    snapshot=BankReconciliationSnapshot(
        company_id=company_id,bank_account_id=bank_account_id,import_id=import_id,
        period_start=period_start,period_end=period_end,
        statement_opening_balance=opening,statement_closing_balance=closing,
        statement_net_movement=statement_net,ledger_net_movement=ledger_net,
        balance_difference=balance_difference,net_difference=difference,statement_line_count=len(lines),
        matched_line_count=matched_count,unmatched_line_count=unmatched_count,
        duplicate_line_count=duplicate_count,ignored_line_count=ignored_count,
        unmatched_ledger_count=unmatched_ledger,status=status,
        reconciled_by_name=actor,note=(note.strip() or None) if note else None)
    session.add(snapshot)
    session.flush()
    return snapshot
