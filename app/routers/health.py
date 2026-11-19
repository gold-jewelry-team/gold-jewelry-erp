from fastapi import APIRouter
from fastapi.responses import JSONResponse
from sqlalchemy.exc import SQLAlchemyError

from app.db.session import check_database_connection

router = APIRouter(tags=["health"])


@router.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/health/db")
def health_db() -> JSONResponse:
    try:
        check_database_connection()
        return JSONResponse(status_code=200, content={"status": "ok", "database": "connected"})
    except SQLAlchemyError:
        return JSONResponse(status_code=503, content={"status": "error", "database": "disconnected"})
