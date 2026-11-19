"""Read-only bank reconciliation report and CSV export endpoints."""
import csv
from datetime import date
from io import StringIO
from uuid import UUID
from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session
from app.db.session import SessionLocal
from app.services.bank_reconciliation_reports import build_bank_reconciliation_report

router = APIRouter(
    prefix="/companies/{company_id}/bank-accounts/{account_id}/reconciliation-report",
    tags=["bank reconciliation reports"],
)


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def _report(company_id, account_id, period_start, period_end, db):
    try:
        return build_bank_reconciliation_report(
            db,
            company_id=company_id,
            bank_account_id=account_id,
            period_start=period_start,
            period_end=period_end,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=404 if "不存在" in str(exc) else 422,
            detail=str(exc),
        ) from exc


def safe_csv_text(value: str) -> str:
    """Neutralize spreadsheet formula prefixes in untrusted text cells."""
    candidate = value.lstrip(" \t\r\n")
    if candidate.startswith(("=", "+", "-", "@", "\t", "\r")):
        return "'" + value
    return value


@router.get("")
def get_report(
    company_id: UUID,
    account_id: UUID,
    period_start: date = Query(...),
    period_end: date = Query(...),
    db: Session = Depends(get_db),
):
    return _report(company_id, account_id, period_start, period_end, db)


@router.get("/export.csv")
def export_report_csv(
    company_id: UUID,
    account_id: UUID,
    period_start: date = Query(...),
    period_end: date = Query(...),
    db: Session = Depends(get_db),
):
    report = _report(company_id, account_id, period_start, period_end, db)
    output = StringIO()
    writer = csv.writer(output)
    writer.writerow(["項目", "數值"])
    writer.writerow(["銀行", safe_csv_text(str(report["bank_name"]))])
    writer.writerow(["帳戶", safe_csv_text(str(report["account_name"]))])
    writer.writerow(["帳號末四碼", safe_csv_text(str(report["account_last4"]))])
    writer.writerow(["對帳期間", f"{period_start.isoformat()} ~ {period_end.isoformat()}"])
    writer.writerow(["對帳單明細筆數", report["statement_line_count"]])
    for key, label in (
        ("MATCHED", "已配對"),
        ("UNMATCHED", "未配對"),
        ("DUPLICATE", "重複"),
        ("IGNORED", "已忽略"),
    ):
        writer.writerow([label, report["status_counts"][key]])
    writer.writerow(["銀行收入合計", report["statement_in_amount"]])
    writer.writerow(["銀行支出合計", report["statement_out_amount"]])
    writer.writerow(["銀行淨變動", report["statement_net_amount"]])
    writer.writerow([])
    writer.writerow(["調整類型", "收入", "支出", "筆數"])
    for row in report["adjustments"]:
        writer.writerow([
            safe_csv_text(str(row["transaction_type"])),
            row["in_amount"],
            row["out_amount"],
            row["count"],
        ])
    snap = report["latest_snapshot"]
    writer.writerow([])
    writer.writerow(["最新快照狀態", safe_csv_text(str(snap["status"])) if snap else "尚無快照"])
    if snap:
        writer.writerow(["帳單與流水差異", snap["net_difference"]])
        writer.writerow(["期初期末餘額差異", snap["balance_difference"]])
        writer.writerow(["未配對銀行流水", snap["unmatched_ledger_count"]])
    output.seek(0)
    filename = f"bank-reconciliation-{period_start.isoformat()}-{period_end.isoformat()}.csv"
    return StreamingResponse(
        iter([output.getvalue().encode("utf-8-sig")]),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
