from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse

from app.core.config import settings
from app.routers.health import router as health_router
from app.routers.company_setup import router as company_setup_router
from app.routers.product_master import router as product_master_router
from app.routers.gold_prices import router as gold_prices_router
from app.routers.suppliers import router as suppliers_router
from app.routers.purchases import router as purchases_router
from app.routers.inventory import router as inventory_router
from app.routers.sales import router as sales_router
from app.routers.sales_returns import router as sales_returns_router
from app.routers.daily_closing import router as daily_closing_router
from app.routers.payments import router as payments_router
from app.routers.supplier_payables import router as supplier_payables_router
from app.routers.expenses import router as expenses_router
from app.routers.cash_counts import router as cash_counts_router
from app.routers.cash_drawer_movements import router as cash_drawer_movements_router
from app.routers.bank_accounts import router as bank_accounts_router
from app.routers.bank_reconciliation import router as bank_reconciliation_router
from app.routers.bank_reconciliation_snapshots import router as bank_reconciliation_snapshots_router
from app.routers.bank_reconciliation_reports import router as bank_reconciliation_reports_router

app = FastAPI(
    title=settings.app_name,
    version="0.1.0",
    description="黃金珠寶進銷存暨營運管理系統 API",
)
app.include_router(health_router)
app.include_router(company_setup_router)
app.include_router(product_master_router)
app.include_router(gold_prices_router)
app.include_router(suppliers_router)
app.include_router(purchases_router)
app.include_router(inventory_router)
app.include_router(sales_router)
app.include_router(sales_returns_router)
app.include_router(daily_closing_router)
app.include_router(payments_router)
app.include_router(supplier_payables_router)
app.include_router(expenses_router)
app.include_router(cash_counts_router)
app.include_router(cash_drawer_movements_router)
app.include_router(bank_accounts_router)
app.include_router(bank_reconciliation_router)
app.include_router(bank_reconciliation_snapshots_router)
app.include_router(bank_reconciliation_reports_router)


@app.get("/", tags=["system"])
def root() -> dict[str, str]:
    return {"name": settings.app_name, "status": "ok", "docs": "/docs"}


@app.get("/app", tags=["workspace"], include_in_schema=False)
def mobile_workspace() -> FileResponse:
    """Serve the mobile-first product and category workspace."""
    return FileResponse(Path(__file__).parent / "static" / "index.html")
