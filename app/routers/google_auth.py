"""Google OpenID Connect login.

Google identities receive a revocable server-side session, but this phase
intentionally does not grant access to business pages or business APIs.
"""
import hashlib
import secrets
from datetime import datetime, timedelta, timezone
from urllib.parse import urlencode

import requests
from google.auth.exceptions import GoogleAuthError
from fastapi import APIRouter, HTTPException, Request, Response
from fastapi.responses import RedirectResponse
from google.auth.transport.requests import Request as GoogleRequest
from google.oauth2 import id_token
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError

from app.core.config import settings
from app.db.session import SessionLocal
from app.models import AuthIdentity, Company, CompanyMembership, User, UserSession

router = APIRouter(prefix="/auth/google", tags=["Google authentication"])

GOOGLE_AUTHORIZATION_ENDPOINT = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_TOKEN_ENDPOINT = "https://oauth2.googleapis.com/token"
OAUTH_COOKIE_MAX_AGE = 600


def _oauth_ready() -> None:
    if not settings.google_oauth_configured:
        raise HTTPException(status_code=503, detail="Google 登入尚未啟用或尚未完成部署設定。")
    # Do not start OAuth until migration 0034 is present in this database.
    try:
        with SessionLocal() as db:
            db.scalar(select(UserSession.id).limit(1))
    except SQLAlchemyError:
        raise HTTPException(status_code=503, detail="Google 登入資料庫尚未完成設定。")


def _cookie_options(*, max_age: int, same_site: str = "lax") -> dict:
    return {
        "max_age": max_age,
        "httponly": True,
        "secure": settings.session_cookie_secure,
        "samesite": same_site,
        "path": "/auth/google",
    }


def _clear_flow_cookies(response: Response) -> None:
    for name in ("google_oauth_state", "google_oauth_nonce", "google_oauth_verifier"):
        response.delete_cookie(name, path="/auth/google", secure=settings.session_cookie_secure, httponly=True, samesite="lax")


@router.get("/config")
def google_login_config() -> dict[str, bool]:
    if not settings.google_oauth_configured:
        return {"enabled": False}
    try:
        with SessionLocal() as db:
            db.scalar(select(UserSession.id).limit(1))
        return {"enabled": True}
    except SQLAlchemyError:
        return {"enabled": False}


@router.get("/start")
def start_google_login():
    _oauth_ready()
    state = secrets.token_urlsafe(32)
    nonce = secrets.token_urlsafe(32)
    verifier = secrets.token_urlsafe(64)
    challenge = __import__("base64").urlsafe_b64encode(
        hashlib.sha256(verifier.encode("ascii")).digest()
    ).decode("ascii").rstrip("=")
    params = {
        "client_id": settings.google_client_id,
        "redirect_uri": settings.google_redirect_uri,
        "response_type": "code",
        "scope": "openid email profile",
        "state": state,
        "nonce": nonce,
        "code_challenge": challenge,
        "code_challenge_method": "S256",
        "prompt": "select_account",
    }
    redirect = RedirectResponse(f"{GOOGLE_AUTHORIZATION_ENDPOINT}?{urlencode(params)}", status_code=302)
    for name, value in (
        ("google_oauth_state", state),
        ("google_oauth_nonce", nonce),
        ("google_oauth_verifier", verifier),
    ):
        redirect.set_cookie(name, value, **_cookie_options(max_age=OAUTH_COOKIE_MAX_AGE))
    return redirect


@router.get("/callback")
def google_callback(request: Request):
    _oauth_ready()
    state = request.query_params.get("state", "")
    code = request.query_params.get("code", "")
    if not code or not state or not secrets.compare_digest(
        state, request.cookies.get("google_oauth_state", "")
    ):
        raise HTTPException(status_code=400, detail="Google 登入驗證失敗，請重新操作。")

    verifier = request.cookies.get("google_oauth_verifier", "")
    expected_nonce = request.cookies.get("google_oauth_nonce", "")
    if not verifier or not expected_nonce:
        raise HTTPException(status_code=400, detail="Google 登入驗證已逾時，請重新操作。")

    try:
        token_response = requests.post(
            GOOGLE_TOKEN_ENDPOINT,
            data={
                "code": code,
                "client_id": settings.google_client_id,
                "client_secret": settings.google_client_secret,
                "redirect_uri": settings.google_redirect_uri,
                "grant_type": "authorization_code",
                "code_verifier": verifier,
            },
            timeout=10,
        )
        token_response.raise_for_status()
        token_payload = token_response.json()
        raw_id_token = token_payload.get("id_token")
        if not raw_id_token:
            raise ValueError("Missing ID token")
        claims = id_token.verify_oauth2_token(
            raw_id_token, GoogleRequest(), settings.google_client_id
        )
        if claims.get("iss") not in ("accounts.google.com", "https://accounts.google.com"):
            raise ValueError("Invalid issuer")
        if not secrets.compare_digest(str(claims.get("nonce", "")), expected_nonce):
            raise ValueError("Invalid nonce")
        if claims.get("email_verified") is not True:
            raise ValueError("Email is not verified")
        subject = str(claims.get("sub", "")).strip()
        email = str(claims.get("email", "")).strip().lower()
        display_name = str(claims.get("name") or email or "Google 使用者").strip()[:120]
        if not subject or not email:
            raise ValueError("Missing identity claims")
    except (requests.RequestException, GoogleAuthError, ValueError, KeyError, TypeError):
        raise HTTPException(status_code=401, detail="無法驗證 Google 帳號，請重新登入。")

    raw_session_token = secrets.token_urlsafe(48)
    token_hash = hashlib.sha256(raw_session_token.encode("utf-8")).hexdigest()
    now = datetime.now(timezone.utc)
    expires_at = now + timedelta(seconds=settings.google_session_max_age_seconds)

    try:
        with SessionLocal() as db:
            identity = db.scalar(
                select(AuthIdentity).where(
                    AuthIdentity.provider == "GOOGLE",
                    AuthIdentity.provider_subject == subject,
                )
            )
            if identity:
                user = db.get(User, identity.user_id)
                if user is None or not user.is_active:
                    raise HTTPException(status_code=403, detail="此帳號目前無法使用，請聯絡管理者。")
                identity.provider_email = email
                identity.email_verified = True
            else:
                user = User(display_name=display_name, email=email, is_active=True)
                db.add(user)
                db.flush()
                db.add(AuthIdentity(
                    user_id=user.id,
                    provider="GOOGLE",
                    provider_subject=subject,
                    provider_email=email,
                    email_verified=True,
                ))
                active_companies = list(db.scalars(
                    select(Company).where(Company.is_active.is_(True)).limit(2)
                ))
                # Only a single active company can be assigned automatically.
                # Zero or multiple companies require a future administrator action.
                if len(active_companies) == 1:
                    db.add(CompanyMembership(
                        company_id=active_companies[0].id,
                        user_id=user.id,
                        status="PENDING",
                        role="STAFF",
                    ))

            if identity is not None:
                membership_statuses = list(db.scalars(
                    select(CompanyMembership.status).where(
                        CompanyMembership.user_id == user.id
                    )
                ))
                if membership_statuses and not any(
                    status in {"ACTIVE", "PENDING"} for status in membership_statuses
                ):
                    raise HTTPException(
                        status_code=403,
                        detail="此帳號目前沒有可使用的公司成員資格，請聯絡管理者。",
                    )

            db.add(UserSession(
                user_id=user.id,
                token_hash=token_hash,
                expires_at=expires_at,
            ))
            db.commit()
    except HTTPException:
        raise
    except SQLAlchemyError:
        # Includes missing 0034 tables: fail closed and keep the old admin login usable.
        raise HTTPException(status_code=503, detail="Google 登入服務尚未完成資料庫設定，請稍後再試。")

    redirect = RedirectResponse("/login?google=connected", status_code=303)
    redirect.set_cookie(
        settings.google_session_cookie_name,
        raw_session_token,
        max_age=settings.google_session_max_age_seconds,
        httponly=True,
        secure=settings.session_cookie_secure,
        samesite="lax",
        path="/auth/google",
    )
    _clear_flow_cookies(redirect)
    return redirect


@router.get("/status")
def google_login_status(request: Request) -> dict:
    raw_token = request.cookies.get(settings.google_session_cookie_name, "")
    if not raw_token:
        raise HTTPException(status_code=401, detail="尚未使用 Google 帳號登入。")
    token_hash = hashlib.sha256(raw_token.encode("utf-8")).hexdigest()
    now = datetime.now(timezone.utc)
    try:
        with SessionLocal() as db:
            session = db.scalar(select(UserSession).where(
                UserSession.token_hash == token_hash,
                UserSession.revoked_at.is_(None),
                UserSession.expires_at > now,
            ))
            if session is None:
                raise HTTPException(status_code=401, detail="登入已失效，請重新登入。")
            user = db.get(User, session.user_id)
            if user is None or not user.is_active:
                raise HTTPException(status_code=403, detail="此帳號目前無法使用。")
            memberships = list(db.scalars(select(CompanyMembership).where(
                CompanyMembership.user_id == user.id
            )))
            if not memberships:
                status = "NEEDS_COMPANY_ASSIGNMENT"
            elif any(item.status == "ACTIVE" for item in memberships):
                status = "APPROVED_BUT_NOT_OPEN"
            elif any(item.status == "PENDING" for item in memberships):
                status = "PENDING_APPROVAL"
            elif any(item.status == "SUSPENDED" for item in memberships):
                status = "SUSPENDED"
            else:
                status = "REJECTED"
            session.last_seen_at = now
            db.commit()
            return {"authenticated": True, "display_name": user.display_name, "status": status}
    except HTTPException:
        raise
    except SQLAlchemyError:
        raise HTTPException(status_code=503, detail="Google 登入資料庫尚未完成設定。")


@router.post("/logout")
def google_logout(request: Request, response: Response) -> dict[str, bool]:
    raw_token = request.cookies.get(settings.google_session_cookie_name, "")
    if raw_token:
        token_hash = hashlib.sha256(raw_token.encode("utf-8")).hexdigest()
        try:
            with SessionLocal() as db:
                session = db.scalar(select(UserSession).where(UserSession.token_hash == token_hash))
                if session and session.revoked_at is None:
                    session.revoked_at = datetime.now(timezone.utc)
                    db.commit()
        except SQLAlchemyError:
            # Cookie is still cleared; server-side expiry remains a backstop.
            pass
    response.delete_cookie(
        settings.google_session_cookie_name,
        path="/auth/google",
        secure=settings.session_cookie_secure,
        httponly=True,
        samesite="lax",
    )
    response.headers["Cache-Control"] = "no-store"
    return {"authenticated": False}
