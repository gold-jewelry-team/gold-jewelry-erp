"""Read-only bank reconciliation reporting queries."""
from datetime import date, datetime, time, timedelta
from decimal import Decimal
from uuid import UUID
from zoneinfo import ZoneInfo
from sqlalchemy import select
from sqlalchemy.orm import Session
from app.models.bank_account import BankAccount, BankTransaction
from app.models.bank_statement import BankStatementLine
from app.models.bank_reconciliation import BankReconciliationSnapshot

TAIPEI=ZoneInfo("Asia/Taipei")
UTC=ZoneInfo("UTC")

def build_bank_reconciliation_report(session:Session,*,company_id:UUID,bank_account_id:UUID,
    period_start:date,period_end:date)->dict:
    if period_end<period_start:
        raise ValueError("報表結束日不可早於開始日。")
    account=session.execute(select(BankAccount).where(
        BankAccount.id==bank_account_id,BankAccount.company_id==company_id
    )).scalar_one_or_none()
    if account is None:
        raise ValueError("銀行帳戶不存在或不屬於此公司。")
    lines=list(session.scalars(select(BankStatementLine).where(
        BankStatementLine.company_id==company_id,
        BankStatementLine.bank_account_id==bank_account_id,
        BankStatementLine.transaction_date>=period_start,
        BankStatementLine.transaction_date<=period_end
    )).all())
    start=datetime.combine(period_start,time.min,tzinfo=TAIPEI).astimezone(UTC)
    end=datetime.combine(period_end+timedelta(days=1),time.min,tzinfo=TAIPEI).astimezone(UTC)
    transactions=list(session.scalars(select(BankTransaction).where(
        BankTransaction.company_id==company_id,
        BankTransaction.bank_account_id==bank_account_id,
        BankTransaction.occurred_at>=start,
        BankTransaction.occurred_at<end
    )).all())
    status_counts={key:sum(1 for row in lines if row.status==key)
        for key in ("MATCHED","UNMATCHED","DUPLICATE","IGNORED")}
    statement_in=sum((row.amount for row in lines if row.direction=="IN" and row.status!="DUPLICATE"),Decimal("0.00"))
    statement_out=sum((row.amount for row in lines if row.direction=="OUT" and row.status!="DUPLICATE"),Decimal("0.00"))
    adjustment_types=("BANK_FEE","INTEREST_IN","OTHER_ADJUSTMENT")
    adjustments=[]
    for kind in adjustment_types:
        rows=[tx for tx in transactions if tx.transaction_type==kind]
        adjustments.append({"transaction_type":kind,
            "in_amount":sum((tx.amount for tx in rows if tx.direction=="IN"),Decimal("0.00")),
            "out_amount":sum((tx.amount for tx in rows if tx.direction=="OUT"),Decimal("0.00")),
            "count":len(rows)})
    snapshot=session.execute(select(BankReconciliationSnapshot).where(
        BankReconciliationSnapshot.company_id==company_id,
        BankReconciliationSnapshot.bank_account_id==bank_account_id,
        BankReconciliationSnapshot.period_start==period_start,
        BankReconciliationSnapshot.period_end==period_end
    ).order_by(BankReconciliationSnapshot.created_at.desc()).limit(1)).scalar_one_or_none()
    return {
        "company_id":company_id,"bank_account_id":bank_account_id,
        "bank_name":account.bank_name,"account_name":account.account_name,
        "account_last4":account.account_last4,"period_start":period_start,"period_end":period_end,
        "statement_line_count":len(lines),"status_counts":status_counts,
        "statement_in_amount":statement_in,"statement_out_amount":statement_out,
        "statement_net_amount":statement_in-statement_out,
        "adjustments":adjustments,
        "latest_snapshot":None if snapshot is None else {
            "id":snapshot.id,"status":snapshot.status,"created_at":snapshot.created_at,
            "statement_net_movement":snapshot.statement_net_movement,
            "ledger_net_movement":snapshot.ledger_net_movement,
            "net_difference":snapshot.net_difference,
            "balance_difference":snapshot.balance_difference,
            "unmatched_ledger_count":snapshot.unmatched_ledger_count,
            "reconciled_by_name":snapshot.reconciled_by_name,
        }
    }
