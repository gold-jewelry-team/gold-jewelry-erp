import re

from fastapi.testclient import TestClient

from app.main import app


def test_home_dashboard_prioritizes_six_daily_tasks_and_folds_secondary_tools():
    response = TestClient(app).get("/app")
    assert response.status_code == 200
    html = response.text

    start = html.index('<div class="home-actions">')
    end = html.index("</div>", start)
    primary_actions = html[start:end]
    assert primary_actions.count("home-action-primary") == 6
    for label in (
        "開始銷售",
        "查商品／庫存",
        "進貨／到貨",
        "開始盤點",
        "今日金價",
        "打烊結帳",
    ):
        assert label in primary_actions

    assert '<details class="home-more">' in html
    assert "<summary><strong>其他功能與查詢</strong>" in html
    for label in (
        "交易紀錄／退貨",
        "客戶訂單",
        "新增商品",
        "供應商帳款",
        "營業費用",
        "現金櫃異動",
        "營運報表",
        "銀行帳戶／對帳",
        "金料往來",
    ):
        assert label in html


def test_every_home_shortcut_target_resolves_to_one_unique_element():
    html = TestClient(app).get("/app").text
    ids = re.findall(r'\bid="([^"]+)"', html)
    targets = re.findall(r'data-home-target="([^"]+)"', html)

    assert targets
    for target in set(targets):
        assert target in ids, f"missing home shortcut target: {target}"
        assert ids.count(target) == 1, f"home target must be unique: {target}"


def test_sales_workflow_explains_stock_commit_and_moves_to_actual_payment():
    html = TestClient(app).get("/app").text
    assert 'class="sale-workflow-guide"' in html
    assert "建立草稿不會扣庫存" in html
    assert "按下「確認成交」才會扣除正式商品庫存" in html
    assert "<li>登錄實際收付款</li>" in html

    draft_start = html.index('$("createSaleDraft").addEventListener("click"')
    draft_end = html.index('$("completeSale").addEventListener("click"', draft_start)
    draft_handler = html[draft_start:draft_end]
    assert '$("saleDraftActions")' in draft_handler
    assert '$("completeSale")' in draft_handler
    assert "scrollIntoView" in draft_handler

    complete_start = html.index('$("completeSale").addEventListener("click"')
    complete_end = html.index('$("voidSale").addEventListener("click"', complete_start)
    complete_handler = html[complete_start:complete_end]
    assert '$("salePaymentPanel")' in complete_handler
    assert '$("salePaymentAmount")' in complete_handler
    assert "scrollIntoView" in complete_handler


def test_purchase_and_stocktake_workflows_move_to_the_next_action():
    html = TestClient(app).get("/app").text
    purchase_start = html.index('$("createPurchase").addEventListener("click"')
    purchase_end = html.index('$("purchaseFilterStatus").addEventListener', purchase_start)
    purchase_handler = html[purchase_start:purchase_end]
    assert '$("purchaseList")' in purchase_handler
    assert "[data-submit-purchase]" in purchase_handler
    assert "scrollIntoView" in purchase_handler

    receive_start = html.index('if(receive){', html.index('$("purchaseList").addEventListener("click"'))
    receive_end = html.index("\n});", receive_start)
    receive_handler = html[receive_start:receive_end]
    assert "[data-receive-line]" in receive_handler
    assert "firstLineButton.focus" in receive_handler

    stocktake_start = html.index('$("stocktakeLocation").addEventListener("change"')
    stocktake_end = html.index('$("stocktakeBarcode").addEventListener', stocktake_start)
    stocktake_handler = html[stocktake_start:stocktake_end]
    assert '$("stocktakeBarcode").focus()' in stocktake_handler


def test_mobile_bank_balance_stays_visible_and_secondary_workflows_are_folded():
    banking = TestClient(app).get("/banking").text
    assert 'id="accountList"' in banking
    assert 'if(panel.querySelector("#accountList"))return;' in banking
    assert "mobile-bank-details" in banking
    assert 'id="companySelect"' in banking


def test_mobile_report_details_are_tap_to_expand_and_visible_newline_tokens_are_removed():
    reports = TestClient(app).get("/reports").text
    assert "mobile-report-details" in reports
    assert "sections.slice(2).forEach" in reports
    assert "銀行存提款與現金櫃連動核對" in reports
    assert r"</section>\n<section" not in reports


def test_common_operational_forms_prefill_dates_and_editable_document_numbers():
    html = TestClient(app).get("/app").text
    assert "function createDocumentNumber(prefix)" in html
    assert '$("purchaseOrderDate").value=taipeiDateValue()' in html
    assert '$("expenseDate").value=taipeiDateValue()' in html
    assert '$("purchaseNo").value=createDocumentNumber("PO")' in html
    assert '$("expenseNo").value=createDocumentNumber("EXP")' in html
    assert '$("billNo").value=createDocumentNumber("BILL")' in html
    assert "採購單號（自動產生，可修改）" in html
    assert "費用單號（自動產生，可修改）" in html
    assert "供應商帳單號碼（自動產生，可修改）" in html

    assert '$("supplierPaymentNo").value=pending.payload.payment_no' in html
    assert '$("supplierPaymentNo").value=createDocumentNumber("PAY")' in html
    assert 'if(!pending&&typeof $("supplierPaymentAmount").focus==="function")' in html


def test_home_landing_screen_keeps_the_long_sales_workspace_closed_until_selected():
    html = TestClient(app).get("/app").text
    assert 'id="quoteWorkbenchPanel"' in html
    assert 'if(!firstInCategory||panel.id==="quoteWorkbenchPanel")' in html
    assert 'class="panel-toggle secondary"' in html
    assert 'target.classList.contains("panel-collapsed")' in html
    assert "const panelsToExpand=[owningPanel,target]" in html
