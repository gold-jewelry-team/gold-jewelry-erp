from fastapi.testclient import TestClient

from app.core.config import settings
from app.main import app

client = TestClient(app)


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
    monkeypatch.setattr(settings, "environment", "production")
    monkeypatch.setattr(settings, "admin_username", "owner")
    monkeypatch.setattr(settings, "admin_password", "test-password-12345")
    monkeypatch.setattr(settings, "session_secret_key", "test-session-secret-key-at-least-32-chars")
    monkeypatch.setattr(settings, "session_cookie_secure", False)
    monkeypatch.setattr(settings, "session_max_age_seconds", 3600)
    monkeypatch.setattr(settings, "app_maintenance_mode", False)

    unauthenticated = client.get("/app", follow_redirects=False)
    assert unauthenticated.status_code == 303
    assert unauthenticated.headers["location"] == "/login"

    denied = client.get("/auth/me")
    assert denied.status_code == 401

    bad_login = client.post("/auth/login", json={"username": "owner", "password": "wrong-password"})
    assert bad_login.status_code == 401

    login = client.post(
        "/auth/login",
        json={"username": "owner", "password": "test-password-12345"},
    )
    assert login.status_code == 200
    assert login.json() == {"authenticated": True}
    assert settings.session_cookie_name in login.cookies

    current = client.get("/auth/me")
    assert current.status_code == 200
    assert current.json() == {"username": "owner", "role": "administrator"}

    logout = client.post("/auth/logout")
    assert logout.status_code == 200
    assert client.get("/auth/me").status_code == 401


def test_health_remains_public_when_auth_is_enabled(monkeypatch) -> None:
    monkeypatch.setattr(settings, "environment", "production")
    monkeypatch.setattr(settings, "admin_username", "owner")
    monkeypatch.setattr(settings, "admin_password", "test-password-12345")
    monkeypatch.setattr(settings, "session_secret_key", "test-session-secret-key-at-least-32-chars")
    monkeypatch.setattr(settings, "app_maintenance_mode", False)

    response = client.get("/health")
    assert response.status_code == 200
