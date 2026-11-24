"""Process-local brute-force protection for the single-admin login endpoint.

The current Render service runs one web instance and one Uvicorn worker. If the
service is scaled horizontally or multiple workers are introduced, replace this
store with a shared rate-limit backend (for example, Render Key Value).
"""
from collections import deque
from dataclasses import dataclass, field
import hashlib
import hmac
import ipaddress
import math
from threading import Lock
import time

from fastapi import Request

from app.core.config import settings

MAX_FAILED_ATTEMPTS = 5
ATTEMPT_WINDOW_SECONDS = 15 * 60
LOCKOUT_SECONDS = 15 * 60
MAX_TRACKED_CLIENTS = 10_000


@dataclass
class _ClientAttempts:
    failed_at: deque[float] = field(default_factory=deque)
    locked_until: float = 0.0


_attempts: dict[str, _ClientAttempts] = {}
_guard = Lock()


def _client_fingerprint(request: Request) -> str:
    """Return a keyed, non-reversible identifier; do not retain raw IP addresses."""
    candidate = request.headers.get("cf-connecting-ip", "").strip()
    if not candidate and request.client is not None:
        candidate = request.client.host

    try:
        client_ip = ipaddress.ip_address(candidate).compressed
    except ValueError:
        client_ip = "unknown"

    return hmac.new(
        settings.session_secret_key.encode("utf-8"),
        client_ip.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()


def _prune_state(state: _ClientAttempts, now: float) -> None:
    if state.locked_until and state.locked_until <= now:
        state.locked_until = 0.0
        state.failed_at.clear()
        return

    cutoff = now - ATTEMPT_WINDOW_SECONDS
    while state.failed_at and state.failed_at[0] <= cutoff:
        state.failed_at.popleft()


def _cleanup(now: float) -> None:
    for key, state in list(_attempts.items()):
        _prune_state(state, now)
        if not state.failed_at and not state.locked_until:
            _attempts.pop(key, None)

    # Keep the in-process cache bounded. Under an unusually large number of
    # distinct clients, evict the oldest entries rather than grow without limit.
    while len(_attempts) > MAX_TRACKED_CLIENTS:
        _attempts.pop(next(iter(_attempts)))


def get_login_retry_after(request: Request, now: float | None = None) -> int:
    current = time.monotonic() if now is None else float(now)
    fingerprint = _client_fingerprint(request)

    with _guard:
        state = _attempts.get(fingerprint)
        if state is None:
            return 0

        _prune_state(state, current)
        if state.locked_until > current:
            return max(1, math.ceil(state.locked_until - current))

        if not state.failed_at and not state.locked_until:
            _attempts.pop(fingerprint, None)
        return 0


def record_failed_login(request: Request, now: float | None = None) -> int:
    """Record a failure and return the lockout duration, or zero if not locked."""
    current = time.monotonic() if now is None else float(now)
    fingerprint = _client_fingerprint(request)

    with _guard:
        _cleanup(current)
        state = _attempts.setdefault(fingerprint, _ClientAttempts())
        _prune_state(state, current)
        state.failed_at.append(current)

        if len(state.failed_at) >= MAX_FAILED_ATTEMPTS:
            state.failed_at.clear()
            state.locked_until = current + LOCKOUT_SECONDS
            return LOCKOUT_SECONDS

        return 0


def clear_login_failures(request: Request) -> None:
    fingerprint = _client_fingerprint(request)
    with _guard:
        _attempts.pop(fingerprint, None)


def reset_login_rate_limits() -> None:
    """Clear process-local state; intended for isolated automated tests."""
    with _guard:
        _attempts.clear()
