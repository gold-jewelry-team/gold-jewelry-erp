"""CSV import and controlled matching for bank statement lines."""
import csv
import hashlib
import io
from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo
from decimal import Decimal, InvalidOperation
from uuid import UUID
from sqlalchemy import select
from sqlalchemy.orm import Session
from app.models.bank_account import BankAccount, BankTransaction
from app.models.bank_statement import BankStatementImport, BankStatementLine

REQUIRED_HEADERS={"transaction_date","description","amount","direction"}
TAIPEI=ZoneInfo("Asia/Taipei")
UTC=ZoneInfo("UTC")

def _fingerprint(day: date, description: str, amount: Decimal, direction: str, reference: str | None) -> str:
    raw="|".join([day.isoformat(),description.strip(),format(amount,".2f"),direction,reference or ""])
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()

def import_bank_statement_csv(session: Session, *, company_id: UUID, bank_account_id: UUID,
                              csv_content: str, source_file_name: str, imported_by_name: str) -> BankStatementImport:
    account=session.execute(select(BankAccount).where(BankAccount.id==bank_account_id,
        BankAccount.company_id==company_id).with_for_update()).scalar_one_or_none()
    if account is None or not account.is_active:
        raise ValueError("銀行帳戶不存在、非本公司帳戶或已停用。")
    if len(csv_content.encode("utf-8"))>2_000_000:
        raise ValueError("CSV 檔案不可超過 2 MB。")
    actor=imported_by_name.strip()
    if not actor: raise ValueError("匯入人不可空白。")
    try:
        reader=csv.DictReader(io.StringIO(csv_content.lstrip("\ufeff")))
        headers={h.strip() for h in (reader.fieldnames or [])}
        if not REQUIRED_HEADERS.issubset(headers):
            raise ValueError("CSV 必須包含 transaction_date、description、amount、direction 欄位。")
        batch=BankStatementImport(company_id=company_id,bank_account_id=bank_account_id,
            source_file_name=source_file_name.strip() or "statement.csv",row_count=0,
            status="IMPORTED",imported_by_name=actor)
        session.add(batch); session.flush()
        count=0
        for raw in reader:
            row={str(k).strip(): (v or "").strip() for k,v in raw.items() if k is not None}
            try:
                day=date.fromisoformat(row["transaction_date"])
                amount=Decimal(row["amount"].replace(",",""))
            except (ValueError,InvalidOperation,KeyError) as exc:
                raise ValueError("CSV 日期或金額格式錯誤；日期請用 YYYY-MM-DD。") from exc
            direction=row["direction"].upper()
            description=row["description"]
            reference=row.get("reference_no") or None
            if direction not in {"IN","OUT"} or amount<=0 or amount.quantize(Decimal("0.01"))!=amount or not description:
                raise ValueError("CSV 每筆明細必須有正數兩位小數金額、IN/OUT 方向及交易摘要。")
            fingerprint=_fingerprint(day,description,amount,direction,reference)
            duplicate=session.execute(select(BankStatementLine).where(
                BankStatementLine.bank_account_id==bank_account_id,
                BankStatementLine.fingerprint==fingerprint)).scalar_one_or_none()
            line=BankStatementLine(import_id=batch.id,company_id=company_id,bank_account_id=bank_account_id,
                transaction_date=day,description=description,amount=amount,direction=direction,
                reference_no=reference,fingerprint=fingerprint,
                status="DUPLICATE" if duplicate else "UNMATCHED",
                duplicate_of_line_id=duplicate.id if duplicate else None)
            if not duplicate and reference:
                candidates=list(session.scalars(select(BankTransaction).where(
                    BankTransaction.company_id==company_id,
                    BankTransaction.bank_account_id==bank_account_id,
                    BankTransaction.direction==direction,
                    BankTransaction.amount==amount,
                    BankTransaction.reference_no==reference,
                    BankTransaction.occurred_at>=datetime.combine(day,time.min,tzinfo=TAIPEI).astimezone(UTC),
                    BankTransaction.occurred_at<datetime.combine(day+timedelta(days=1),time.min,tzinfo=TAIPEI).astimezone(UTC),
                    ~BankTransaction.id.in_(select(BankStatementLine.matched_bank_transaction_id).where(
                        BankStatementLine.matched_bank_transaction_id.is_not(None))
                    )
                )).all())
                if len(candidates)==1:
                    line.status="MATCHED"
                    line.matched_bank_transaction_id=candidates[0].id
            session.add(line); count+=1
        if count==0: raise ValueError("CSV 沒有可匯入的交易明細。")
        batch.row_count=count
        session.flush()
        return batch
    except csv.Error as exc:
        raise ValueError("CSV 格式無法解析。") from exc

def match_statement_line(session: Session, *, company_id: UUID, line_id: UUID,
                         bank_transaction_id: UUID) -> BankStatementLine:
    line=session.execute(select(BankStatementLine).where(
        BankStatementLine.id==line_id,BankStatementLine.company_id==company_id).with_for_update()).scalar_one_or_none()
    if line is None: raise ValueError("銀行對帳單明細不存在。")
    if line.status!="UNMATCHED": raise ValueError("只有未配對明細可以進行配對。")
    tx=session.execute(select(BankTransaction).where(
        BankTransaction.id==bank_transaction_id,
        BankTransaction.company_id==company_id,
        BankTransaction.bank_account_id==line.bank_account_id).with_for_update()).scalar_one_or_none()
    if tx is None: raise ValueError("銀行流水不存在或不屬於同一銀行帳戶。")
    occurred_at=tx.occurred_at
    if occurred_at.tzinfo is None:
        occurred_at=occurred_at.replace(tzinfo=UTC)
    bank_local_date=occurred_at.astimezone(TAIPEI).date()
    if tx.direction!=line.direction or tx.amount!=line.amount or bank_local_date!=line.transaction_date:
        raise ValueError("銀行流水的日期、方向或金額與對帳單明細不一致。")
    if line.reference_no and tx.reference_no!=line.reference_no:
        raise ValueError("銀行流水參考編號與對帳單不一致。")
    used=session.execute(select(BankStatementLine.id).where(
        BankStatementLine.matched_bank_transaction_id==bank_transaction_id)).scalar_one_or_none()
    if used: raise ValueError("這筆銀行流水已被其他對帳明細配對。")
    line.status="MATCHED"
    line.matched_bank_transaction_id=bank_transaction_id
    session.flush()
    return line

def ignore_statement_line(session: Session, *, company_id: UUID, line_id: UUID) -> BankStatementLine:
    line=session.execute(select(BankStatementLine).where(
        BankStatementLine.id==line_id,BankStatementLine.company_id==company_id).with_for_update()).scalar_one_or_none()
    if line is None: raise ValueError("銀行對帳單明細不存在。")
    if line.status!="UNMATCHED": raise ValueError("只有未配對明細可以標記忽略。")
    line.status="IGNORED"
    session.flush()
    return line


def create_statement_adjustment(session: Session, *, company_id: UUID, import_id: UUID,
    line_id: UUID, transaction_type: str, created_by_name: str, reason: str,
    occurred_at: datetime | None = None) -> BankTransaction:
    """Create an append-only bank ledger adjustment linked to one unmatched statement line."""
    actor=created_by_name.strip()
    memo=reason.strip()
    if not actor:
        raise ValueError("調整人不可空白。")
    if not memo:
        raise ValueError("調整原因不可空白。")
    if transaction_type not in {"BANK_FEE","INTEREST_IN","OTHER_ADJUSTMENT"}:
        raise ValueError("不支援的銀行調整類型。")
    line=session.execute(select(BankStatementLine).where(
        BankStatementLine.id==line_id,
        BankStatementLine.import_id==import_id,
        BankStatementLine.company_id==company_id
    ).with_for_update()).scalar_one_or_none()
    if line is None:
        raise ValueError("對帳單明細不存在或不屬於此匯入批次。")
    if line.status!="UNMATCHED":
        raise ValueError("只有未配對明細可以建立調整流水。")
    account=session.execute(select(BankAccount).where(
        BankAccount.id==line.bank_account_id,
        BankAccount.company_id==company_id
    ).with_for_update()).scalar_one_or_none()
    if account is None or not account.is_active:
        raise ValueError("銀行帳戶不存在或已停用。")
    if transaction_type=="BANK_FEE" and line.direction!="OUT":
        raise ValueError("銀行手續費必須是支出明細。")
    if transaction_type=="INTEREST_IN" and line.direction!="IN":
        raise ValueError("銀行利息收入必須是收入明細。")
    existing=session.execute(select(BankTransaction.id).where(
        BankTransaction.statement_line_id==line.id)).scalar_one_or_none()
    if existing:
        raise ValueError("此對帳單明細已建立調整流水。")
    tx=BankTransaction(
        company_id=company_id,bank_account_id=line.bank_account_id,site_id=None,
        statement_line_id=line.id,transaction_type=transaction_type,
        direction=line.direction,amount=line.amount,currency_code="TWD",
        reference_no=line.reference_no,description=line.description[:200],
        created_by_name=actor,occurred_at=occurred_at or datetime.combine(
            line.transaction_date,datetime.min.time(),tzinfo=TAIPEI),
        note=memo
    )
    session.add(tx)
    session.flush()
    line.status="MATCHED"
    line.matched_bank_transaction_id=tx.id
    session.flush()
    return tx
