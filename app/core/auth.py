import base64
import hashlib
import hmac
import json
import time

from app.core.config import settings


def _b64encode(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).decode("ascii").rstrip("=")


def _b64decode(value: str) -> bytes:
    return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))


def create_session_token(username: str, now: int | None = None) -> str:
    issued_at = int(time.time()) if now is None else int(now)
    payload = json.dumps(
        {
            "sub": username,
            "iat": issued_at,
            "exp": issued_at + settings.session_max_age_seconds,
        },
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    encoded_payload = _b64encode(payload)
    signature = hmac.new(
        settings.session_secret_key.encode("utf-8"),
        encoded_payload.encode("ascii"),
        hashlib.sha256,
    ).digest()
    return f"{encoded_payload}.{_b64encode(signature)}"


def verify_session_token(token: str, now: int | None = None) -> str | None:
    if not settings.auth_configured:
        return None
    try:
        encoded_payload, encoded_signature = token.split(".", 1)
        expected_signature = hmac.new(
            settings.session_secret_key.encode("utf-8"),
            encoded_payload.encode("ascii"),
            hashlib.sha256,
        ).digest()
        supplied_signature = _b64decode(encoded_signature)
        if not hmac.compare_digest(expected_signature, supplied_signature):
            return None

        payload = json.loads(_b64decode(encoded_payload))
        current_time = int(time.time()) if now is None else int(now)
        username = payload.get("sub")
        expires_at = payload.get("exp")
        if (
            username != settings.admin_username
            or not isinstance(expires_at, int)
            or expires_at <= current_time
        ):
            return None
        return username
    except (ValueError, TypeError, KeyError, json.JSONDecodeError):
        return None
