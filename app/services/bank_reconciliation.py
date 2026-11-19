"""CSV import and controlled matching for bank statement lines."""
import csv
import hashlib
import io
from datetime import date, datetime, timezone
from decimal import Decimal, InvalidOperation
from uuid import UUID
from sqlalchemy import select
from sqlalchemy.orm import Session
from app.models.bank_account import BankAccount, BankTransaction
from app.models.bank_statement import BankStatementImport, BankStatementLine

REQUIRED_HEADERS={"transaction_date","description","amount","direction"}

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
                    BankTransaction.occurred_at>=datetime.combine(day,datetime.min.time(),tzinfo=timezone.utc),
                    BankTransaction.occurred_at<datetime.combine(day,datetime.max.time(),tzinfo=timezone.utc),
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
    if tx.direction!=line.direction or tx.amount!=line.amount or tx.occurred_at.date()!=line.transaction_date:
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
