from pathlib import Path

from fastapi.testclient import TestClient

from app.main import app


client = TestClient(app)
STATIC_DIR = Path(__file__).resolve().parents[1] / "app" / "static"
THEME_LINK = '<link rel="stylesheet" href="/theme.css?v=botanical-jewelry-bunny-global-20261127d">'
INDEX_THEME_LINK = THEME_LINK


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
    assert ".bunny-empty-guide" in response.text
    assert ".bunny-empty-art" in response.text
    assert "@media(max-width:480px)" in response.text


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


def test_dutch_rabbit_context_hints_cover_stocktake_zero_stock_and_empty_states() -> None:
    home = (STATIC_DIR / "index.html").read_text(encoding="utf-8")
    theme = (STATIC_DIR / "theme.css").read_text(encoding="utf-8")

    assert "createBunnyContextNote" in home
    assert "renderZeroStockBunnyHint(filtered)" in home
    assert "Number(row.quantity)===0" in home
    assert "補貨小提醒" in home
    assert "盤點任務完成！" in home
    assert 'appliedCount>0&&!pending.length' in home
    assert "bunnyEmptyStockGuide" in home
    assert "bunnyEmptyStocktakeGuide" in home
    assert "bunnyEmptyCategoryGuide" in home
    assert "bunnyEmptyQuoteGuide" in home
    assert "目前查詢範圍有 " in home
    assert ".bunny-context-note" in theme
    assert ".bunny-context-note.is-alert" in theme
    assert ".bunny-context-note.is-success" in theme


def test_dutch_rabbit_shopkeeper_guide_is_present_on_every_static_page() -> None:
    html_pages = sorted(STATIC_DIR.glob("*.html"))
    theme = (STATIC_DIR / "theme.css").read_text(encoding="utf-8")

    for page in html_pages:
        html = page.read_text(encoding="utf-8")
        assert "bunny-page-guide" in html or "bunny-shop-note" in html, (
            f"{page.name} must show the consistent Dutch rabbit shopkeeper mascot."
        )

    assert ".bunny-page-guide" in theme
    assert ".bunny-page-guide-prop" in theme
    assert "position:absolute!important" in theme
    assert "prefers-reduced-motion:no-preference" in theme
    home = (STATIC_DIR / "index.html").read_text(encoding="utf-8")
    assert 'class="bunny-shop-prop"' in home
    assert ".bunny-shop-prop" in home
    assert "bunny-page-guide-art::after" in theme
    assert 'data-scene="banking"' in (STATIC_DIR / "banking.html").read_text(encoding="utf-8")
    assert 'data-scene="sales"' in (STATIC_DIR / "employee_sales.html").read_text(encoding="utf-8")
    assert 'data-scene="permissions"' in (STATIC_DIR / "role_management.html").read_text(encoding="utf-8")
    for page in html_pages:
        if page.name != "index.html":
            html = (STATIC_DIR / page.name).read_text(encoding="utf-8")
            assert 'data-scene="' in html, f"{page.name} must define a contextual mascot scene."
            assert 'class="bunny-page-guide-prop"' in html, f"{page.name} must show its contextual SVG prop."

    for scene in ("banking", "work", "catalog", "orders", "payables", "purchases", "sales", "material", "welcome", "members", "reports", "permissions"):
        assert f'data-scene="{scene}"' in theme, f"Missing contextual accessory for {scene}."

    assert "道奇兔店長小提醒" in " ".join(
        (STATIC_DIR / page.name).read_text(encoding="utf-8")
        for page in html_pages if page.name != "index.html"
    )


def test_employee_and_report_empty_states_show_contextual_dutch_rabbit_guides() -> None:
    theme = (STATIC_DIR / "theme.css").read_text(encoding="utf-8")
    page_expectations = {
        "employee_catalog.html": ["function bunnyEmptyGuide", "沒有找到符合的商品", "沒有找到符合的庫存"],
        "employee_sales.html": ["function bunnyEmptyGuide", "這組條件沒有銷售紀錄", "這筆銷售沒有退貨紀錄"],
        "employee_purchases.html": ["function bunnyEmptyGuide", "沒有符合條件的採購紀錄"],
        "employee_customer_orders.html": ["function bunnyEmptyGuide", "沒有符合條件的客戶訂單", "這筆訂單尚無收退款紀錄"],
        "employee_payables.html": ["function bunnyEmptyGuide", "沒有符合條件的供應商帳單", "沒有符合條件的付款紀錄"],
        "reports.html": ["function bunnyEmptyMarkup", "這段期間沒有營運資料", "目前沒有未結清項目"],
    }

    for filename, expected_strings in page_expectations.items():
        html = (STATIC_DIR / filename).read_text(encoding="utf-8")
        for expected in expected_strings:
            assert expected in html, f"{filename} is missing contextual empty-state guidance: {expected}"

    assert ".bunny-empty-guide" in theme
    assert ".bunny-empty-copy" in theme
    assert ".bunny-empty-token" in theme



def test_scanner_feedback_uses_contextual_dutch_rabbit_and_distinguishes_states() -> None:
    home = (STATIC_DIR / "index.html").read_text(encoding="utf-8")

    assert 'id="scanFeedbackBunny"' in home
    assert "function ensureScanFeedbackBunny" in home
    assert "function showScanNotice" in home
    assert "function showScanFeedback" in home
    assert 'showScanNotice("目前無法使用相機掃描"' in home
    assert 'showScanNotice("相機權限尚未就緒"' in home
    assert 'error.name==="NotAllowedError"' in home
    assert 'error.name==="NotFoundError"' in home
    assert 'error.name==="NotReadableError"' in home
    assert 'const kind=!isError?"success":notFound?"warning":"error"' in home
    assert "setScanFeedbackActionVisibility(false)" in home
    assert "setScanFeedbackActionVisibility(true)" in home
    assert ".scan-feedback.success" in home
    assert ".scan-feedback.warning" in home
    assert ".scan-feedback.error" in home
    assert 'aria-live",kind==="error"?"assertive":"polite"' in home
