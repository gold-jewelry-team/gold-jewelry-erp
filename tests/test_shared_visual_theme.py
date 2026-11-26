from pathlib import Path

from fastapi.testclient import TestClient

from app.main import app


client = TestClient(app)
STATIC_DIR = Path(__file__).resolve().parents[1] / "app" / "static"
THEME_LINK = '<link rel="stylesheet" href="/theme.css?v=warm-20261126">'


def test_shared_theme_stylesheet_is_public_and_served() -> None:
    response = client.get("/theme.css?v=warm-20261126")

    assert response.status_code == 200
    assert "text/css" in response.headers["content-type"]
    assert "--erp-bg:#f5f0e7" in response.text
    assert "--erp-bronze:#79582f" in response.text
    assert "prefers-reduced-motion:reduce" in response.text


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
