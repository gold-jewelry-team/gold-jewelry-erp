import hmac

from fastapi import APIRouter, HTTPException, Request, Response
from pydantic import BaseModel, Field

from app.core.auth import create_session_token
from app.core.config import settings

router = APIRouter(prefix="/auth", tags=["authentication"])


class LoginRequest(BaseModel):
    username: str = Field(min_length=1, max_length=128)
    password: str = Field(min_length=1, max_length=1024)


@router.post("/login")
def login(payload: LoginRequest, response: Response) -> dict[str, bool]:
    if not settings.auth_configured:
        raise HTTPException(status_code=503, detail="管理者登入尚未完成部署設定。")

    username_matches = hmac.compare_digest(
        payload.username.encode("utf-8"),
        settings.admin_username.encode("utf-8"),
    )
    password_matches = hmac.compare_digest(
        payload.password.encode("utf-8"),
        settings.admin_password.encode("utf-8"),
    )
    if not (username_matches and password_matches):
        raise HTTPException(status_code=401, detail="帳號或密碼錯誤。")

    response.set_cookie(
        key=settings.session_cookie_name,
        value=create_session_token(settings.admin_username),
        max_age=settings.session_max_age_seconds,
        httponly=True,
        secure=settings.session_cookie_secure,
        samesite="strict",
        path="/",
    )
    response.headers["Cache-Control"] = "no-store"
    return {"authenticated": True}


@router.get("/me")
def current_admin(request: Request) -> dict[str, str]:
    return {"username": request.state.admin_username, "role": "administrator"}


@router.post("/logout")
def logout(response: Response) -> dict[str, bool]:
    response.delete_cookie(
        key=settings.session_cookie_name,
        path="/",
        httponly=True,
        secure=settings.session_cookie_secure,
        samesite="strict",
    )
    response.headers["Cache-Control"] = "no-store"
    return {"authenticated": False}
