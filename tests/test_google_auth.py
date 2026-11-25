from fastapi.testclient import TestClient

from app.core.config import settings
from app.main import app

client = TestClient(app)


def test_google_login_is_hidden_when_feature_flag_is_off(monkeypatch) -> None:
    monkeypatch.setattr(settings, "google_oauth_enabled", False)
    monkeypatch.setattr(settings, "google_client_id", "")
    monkeypatch.setattr(settings, "google_client_secret", "")
    monkeypatch.setattr(settings, "google_redirect_uri", "")

    response = client.get("/auth/google/config")
    assert response.status_code == 200
    assert response.json() == {"enabled": False}


def test_google_oauth_start_fails_closed_when_not_configured(monkeypatch) -> None:
    monkeypatch.setattr(settings, "google_oauth_enabled", False)

    response = client.get("/auth/google/start")
    assert response.status_code == 503
    assert "尚未啟用" in response.json()["detail"]


def test_google_status_requires_its_own_session_cookie() -> None:
    response = client.get("/auth/google/status")
    assert response.status_code == 401


def test_google_callback_does_not_accept_missing_state(monkeypatch) -> None:
    monkeypatch.setattr(settings, "google_oauth_enabled", False)

    response = client.get("/auth/google/callback?code=fake&state=fake")
    assert response.status_code == 503
