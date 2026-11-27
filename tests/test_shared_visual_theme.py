from pathlib import Path

from fastapi.testclient import TestClient

from app.main import app


client = TestClient(app)
STATIC_DIR = Path(__file__).resolve().parents[1] / "app" / "static"
THEME_LINK = '<link rel="stylesheet" href="/theme.css?v=botanical-20261127b">'
INDEX_THEME_LINK = '<link rel="stylesheet" href="/theme.css?v=botanical-jewelry-20261127c">'


def test_shared_theme_stylesheet_is_public_and_served() -> None:
    response = client.get("/theme.css?v=botanical-20261127b")

    assert response.status_code == 200
    assert "text/css" in response.headers["content-type"]
    assert "--erp-bg:#f6f6ef" in response.text
    assert "--erp-surface:#ffffff" in response.text
    assert "--erp-blue:#66869a" in response.text
    assert "--erp-green:#7b9d87" in response.text
    assert "--erp-green-soft:#edf4ed" in response.text
    assert "--erp-champagne:#d6b875" in response.text
    assert "--green:var(--erp-green-dark)" in response.text
    assert "prefers-reduced-motion:reduce" in response.text
    assert "#e5eee5" in response.text
    assert "header h1{color:#3e4a40}" in response.text
    assert "button.secondary{" in response.text
    assert "background:#edf4ed" in response.text
    assert "radial-gradient(ellipse at 7% 5%" in response.text
    assert "linear-gradient(135deg,#f9f8f2" in response.text


def test_every_static_workspace_page_uses_the_shared_theme() -> None:
    html_pages = sorted(STATIC_DIR.glob("*.html"))

    assert html_pages, "No static workspace HTML pages were found."

    for page in html_pages:
        html = page.read_text(encoding="utf-8")
        expected_link = INDEX_THEME_LINK if page.name == "index.html" else THEME_LINK
        assert html.count(expected_link) == 1, (
            f"{page.name} must load the shared theme exactly once."
        )
        assert html.index(expected_link) < html.lower().index("</head>"), (
            f"{page.name} must load the theme from the document head."
        )


def test_home_workspace_renders_chibi_jewelry_category_illustrations() -> None:
    home = (STATIC_DIR / "index.html").read_text(encoding="utf-8")
    theme = (STATIC_DIR / "theme.css").read_text(encoding="utf-8")

    assert "initJewelryCategoryIllustrations" in home
    assert "productCategoryPreview" in home
    assert "categoryList" in home
    assert "金條|金錠|金磚" in home
    assert "元寶" in home
    assert "金塊|金粒|金礦" in home
    assert "戒指|鑽戒|婚戒" in home
    assert "項鍊|項鏈" in home
    assert "手鍊|手鏈|手環" in home
    assert "耳環|耳針" in home
    assert "寶石|翡翠|玉石" in home
    assert ".jewelry-category-card-head" in theme
    assert ".jewelry-category-preview" in theme
