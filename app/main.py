from fastapi import FastAPI

from app.core.config import settings
from app.routers.health import router as health_router
from app.routers.gold_prices import router as gold_prices_router
from app.routers.suppliers import router as suppliers_router
from app.routers.purchases import router as purchases_router
from app.routers.inventory import router as inventory_router
from app.routers.sales import router as sales_router
from app.routers.sales_returns import router as sales_returns_router
from app.routers.daily_closing import router as daily_closing_router
from app.routers.payments import router as payments_router
from app.routers.supplier_payables import router as supplier_payables_router

app = FastAPI(
    title=settings.app_name,
    version="0.1.0",
    description="黃金珠寶進銷存暨營運管理系統 API",
)
app.include_router(health_router)
app.include_router(gold_prices_router)
app.include_router(suppliers_router)
app.include_router(purchases_router)
app.include_router(inventory_router)
app.include_router(sales_router)
app.include_router(sales_returns_router)
app.include_router(daily_closing_router)
app.include_router(payments_router)
app.include_router(supplier_payables_router)


@app.get("/", tags=["system"])
def root() -> dict[str, str]:
    return {"name": settings.app_name, "status": "ok", "docs": "/docs"}
