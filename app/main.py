from pathlib import Path
from urllib.parse import urlsplit

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse

from app.core.auth import verify_session_token
from app.core.config import settings
from app.routers.auth import router as auth_router
from app.routers.health import router as health_router
from app.routers.company_setup import router as company_setup_router
from app.routers.product_master import router as product_master_router
from app.routers.labor_code_settings import router as labor_code_settings_router
from app.routers.product_code_sequence import router as product_code_sequence_router
from app.routers.gold_prices import router as gold_prices_router
from app.routers.gold_material import router as gold_material_router
from app.routers.supplier_offerings import router as supplier_offerings_router
from app.routers.suppliers import router as suppliers_router
from app.routers.purchases import router as purchases_router
from app.routers.inventory import router as inventory_router
from app.routers.sales import router as sales_router
from app.routers.customer_orders import router as customer_orders_router
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
app.include_router(auth_router)
app.include_router(company_setup_router)
app.include_router(product_master_router)
app.include_router(labor_code_settings_router)
app.include_router(product_code_sequence_router)
app.include_router(gold_prices_router)
app.include_router(gold_material_router)
app.include_router(supplier_offerings_router)
app.include_router(suppliers_router)
app.include_router(purchases_router)
app.include_router(inventory_router)
app.include_router(sales_router)
app.include_router(customer_orders_router)
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


@app.middleware("http")
async def security_middleware(request: Request, call_next):
    """Fail closed in production and protect every app/API route with an admin session."""
    path = request.url.path
    health_paths = {"/health", "/health/db"}

    if settings.app_maintenance_mode and path not in health_paths:
        return JSONResponse(
            status_code=503,
            content={
                "status": "maintenance",
                "message": "系統暫停服務，請稍後再試。",
            },
            headers={"Retry-After": "300"},
        )

    if path in health_paths:
        return await call_next(request)

    if path == "/login":
        return await call_next(request)

    if path == "/auth/login" and request.method == "POST":
        # Login is public, so protect it separately against cross-site submissions.
        origin = request.headers.get("origin")
        fetch_site = request.headers.get("sec-fetch-site", "").lower()
        if (
            (origin and urlsplit(origin).netloc.lower() != request.headers.get("host", "").lower())
            or fetch_site == "cross-site"
        ):
            return JSONResponse(status_code=403, content={"detail": "跨來源請求已拒絕。"})
        return await call_next(request)

    if not settings.auth_enabled:
        return await call_next(request)

    if not settings.auth_configured:
        return JSONResponse(
            status_code=503,
            content={
                "status": "auth_not_configured",
                "message": "管理者登入尚未完成部署設定，系統暫不開放。",
            },
            headers={"Cache-Control": "no-store"},
        )

    if request.method in {"POST", "PUT", "PATCH", "DELETE"}:
        origin = request.headers.get("origin")
        fetch_site = request.headers.get("sec-fetch-site", "").lower()
        if (
            (origin and urlsplit(origin).netloc.lower() != request.headers.get("host", "").lower())
            or fetch_site == "cross-site"
        ):
            return JSONResponse(status_code=403, content={"detail": "跨來源請求已拒絕。"})

    token = request.cookies.get(settings.session_cookie_name, "")
    username = verify_session_token(token) if token else None
    if username:
        request.state.admin_username = username
        return await call_next(request)

    if path == "/app" or path == "/":
        return RedirectResponse(url="/login", status_code=303)

    return JSONResponse(
        status_code=401,
        content={"detail": "請先登入管理者帳號。"},
        headers={"Cache-Control": "no-store"},
    )


@app.get("/login", tags=["authentication"], include_in_schema=False)
def login_page() -> FileResponse:
    return FileResponse(Path(__file__).parent / "static" / "login.html")


@app.get("/", tags=["system"])
def root() -> dict[str, str]:
    return {"name": settings.app_name, "status": "ok", "docs": "/docs"}


@app.get("/app", tags=["workspace"], include_in_schema=False)
def mobile_workspace() -> FileResponse:
    """Serve the mobile-first product and category workspace."""
    return FileResponse(Path(__file__).parent / "static" / "index.html")
