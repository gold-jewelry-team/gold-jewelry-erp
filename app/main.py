from fastapi import FastAPI

from app.core.config import settings
from app.routers.health import router as health_router
from app.routers.gold_prices import router as gold_prices_router
from app.routers.suppliers import router as suppliers_router
from app.routers.purchases import router as purchases_router
from app.routers.inventory import router as inventory_router

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


@app.get("/", tags=["system"])
def root() -> dict[str, str]:
    return {"name": settings.app_name, "status": "ok", "docs": "/docs"}
