from pathlib import Path

from fastapi.testclient import TestClient

from app.main import app


client = TestClient(app)
STATIC_DIR = Path(__file__).resolve().parents[1] / "app" / "static"
THEME_LINK = '<link rel="stylesheet" href="/theme.css?v=bluegreen-20261127a">'


def test_shared_theme_stylesheet_is_public_and_served() -> None:
    response = client.get("/theme.css?v=bluegreen-20261127a")

    assert response.status_code == 200
    assert "text/css" in response.headers["content-type"]
    assert "--erp-bg:#edf5ff" in response.text
    assert "--erp-surface:#ffffff" in response.text
    assert "--erp-blue:#2f65b0" in response.text
    assert "--erp-green:#6f9f8c" in response.text
    assert "--erp-green-soft:#eaf4ef" in response.text
    assert "--erp-champagne:#d6b875" in response.text
    assert "--green:var(--erp-green-dark)" in response.text
    assert "prefers-reduced-motion:reduce" in response.text
    assert "#dceafa" in response.text
    assert "header h1{color:#263b54}" in response.text
    assert "button.secondary{" in response.text
    assert "background:#eaf4ef" in response.text


def test_every_static_workspace_page_uses_the_shared_theme() -> None:
    html_pages = sorted(STATIC_DIR.glob("*.html"))

    assert html_pages, "No static workspace HTML pages were found."

    for page in html_pages:
        html = page.read_text(encoding="utf-8")
        assert html.count(THEME_LINK) == 1, (
            f"{page.name} must load the shared theme exactly once."
        )
        assert html.index(THEME_LINK) < html.lower().index("</head>"), (
            f"{page.name} must load the theme from the document head."
        )
