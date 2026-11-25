import pytest
from fastapi.testclient import TestClient

from app.core.config import settings
from app.core.login_rate_limit import reset_login_rate_limits
from app.main import app

client = TestClient(app)


@pytest.fixture(autouse=True)
def clear_rate_limit_state():
    reset_login_rate_limits()
    yield
    reset_login_rate_limits()


def _configure_auth(monkeypatch) -> None:
    monkeypatch.setattr(settings, "environment", "production")
    monkeypatch.setattr(settings, "admin_username", "owner")
    monkeypatch.setattr(settings, "admin_password", "test-password-12345")
    monkeypatch.setattr(settings, "session_secret_key", "test-session-secret-key-at-least-32-chars")
    monkeypatch.setattr(settings, "session_cookie_secure", False)
    monkeypatch.setattr(settings, "session_max_age_seconds", 3600)
    monkeypatch.setattr(settings, "app_maintenance_mode", False)


def test_production_fails_closed_without_auth_configuration(monkeypatch) -> None:
    monkeypatch.setattr(settings, "environment", "production")
    monkeypatch.setattr(settings, "admin_username", "")
    monkeypatch.setattr(settings, "admin_password", "")
    monkeypatch.setattr(settings, "session_secret_key", "")
    monkeypatch.setattr(settings, "app_maintenance_mode", False)

    response = client.get("/app")
    assert response.status_code == 503
    assert response.json()["status"] == "auth_not_configured"


def test_admin_login_protects_app_and_api(monkeypatch) -> None:
    _configure_auth(monkeypatch)
    test_client = TestClient(app)

    unauthenticated = test_client.get("/app", follow_redirects=False)
    assert unauthenticated.status_code == 303
    assert unauthenticated.headers["location"] == "/login"

    denied = test_client.get("/auth/me")
    assert denied.status_code == 401

    bad_login = test_client.post("/auth/login", json={"username": "owner", "password": "wrong-password"})
    assert bad_login.status_code == 401

    login = test_client.post(
        "/auth/login",
        json={"username": "owner", "password": "test-password-12345"},
    )
    assert login.status_code == 200
    assert login.json() == {"authenticated": True}
    assert settings.session_cookie_name in login.cookies

    current = test_client.get("/auth/me")
    assert current.status_code == 200
    assert current.json() == {"username": "owner", "role": "administrator"}

    workspace = test_client.get("/app")
    assert workspace.status_code == 200

    logout = test_client.post("/auth/logout")
    assert logout.status_code == 200
    assert test_client.get("/auth/me").status_code == 401


def test_role_management_page_is_served_but_role_api_stays_admin_protected(monkeypatch) -> None:
    _configure_auth(monkeypatch)
    test_client = TestClient(app)

    page = test_client.get("/role-management")
    assert page.status_code == 200
    assert "角色與權限管理" in page.text
    assert "/app" in page.text

    denied = test_client.get("/admin/api/companies")
    assert denied.status_code == 401

    login = test_client.post(
        "/auth/login",
        json={"username": "owner", "password": "test-password-12345"},
    )
    assert login.status_code == 200
    allowed = test_client.get("/admin/api/companies")
    assert allowed.status_code == 200


def test_health_remains_public_when_auth_is_enabled(monkeypatch) -> None:
    _configure_auth(monkeypatch)
    response = client.get("/health")
    assert response.status_code == 200


def test_login_is_rate_limited_after_five_failed_attempts(monkeypatch) -> None:
    _configure_auth(monkeypatch)
    test_client = TestClient(app)
    headers = {"cf-connecting-ip": "203.0.113.10"}

    for _ in range(4):
        response = test_client.post(
            "/auth/login",
            headers=headers,
            json={"username": "owner", "password": "wrong-password"},
        )
        assert response.status_code == 401

    limited = test_client.post(
        "/auth/login",
        headers=headers,
        json={"username": "owner", "password": "wrong-password"},
    )
    assert limited.status_code == 429
    assert limited.headers["retry-after"] == "900"

    correct_password_while_locked = test_client.post(
        "/auth/login",
        headers=headers,
        json={"username": "owner", "password": "test-password-12345"},
    )
    assert correct_password_while_locked.status_code == 429


def test_successful_login_clears_previous_failures(monkeypatch) -> None:
    _configure_auth(monkeypatch)
    test_client = TestClient(app)
    headers = {"cf-connecting-ip": "203.0.113.11"}

    for _ in range(4):
        response = test_client.post(
            "/auth/login",
            headers=headers,
            json={"username": "owner", "password": "wrong-password"},
        )
        assert response.status_code == 401

    login = test_client.post(
        "/auth/login",
        headers=headers,
        json={"username": "owner", "password": "test-password-12345"},
    )
    assert login.status_code == 200

    for _ in range(4):
        response = test_client.post(
            "/auth/login",
            headers=headers,
            json={"username": "owner", "password": "wrong-password"},
        )
        assert response.status_code == 401


def test_login_rejects_cross_site_submission(monkeypatch) -> None:
    _configure_auth(monkeypatch)
    response = client.post(
        "/auth/login",
        headers={
            "origin": "https://attacker.example",
            "sec-fetch-site": "cross-site",
        },
        json={"username": "owner", "password": "test-password-12345"},
    )
    assert response.status_code == 403
