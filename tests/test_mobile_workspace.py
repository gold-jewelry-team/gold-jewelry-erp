from fastapi.testclient import TestClient

from app.main import app


def test_mobile_workspace_serves_html():
    response = TestClient(app).get("/app")
    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]
    assert "黃金珠寶進銷存" in response.text
    assert 'id="productForm"' in response.text
    assert "列印 3×10 貼紙" in response.text
    assert "@page{size:100mm 30mm;margin:0}" in response.text
    assert "grid-template-columns:49mm 49mm" in response.text
    assert 'id="labelLotModal"' in response.text
    assert "label-lots" in response.text
    assert "進貨成本工錢" in response.text
    assert "formatLaborDarkCode" in response.text
    assert "formatRocStickerDate" in response.text
    assert "銷售工錢" in response.text
    assert "低於進貨成本工錢" in response.text
    assert "廠商：" in response.text
    assert "櫃位：" in response.text
    assert "進貨日：" in response.text
    assert "款式:" in response.text
    assert "labor-code-config" in response.text
    assert "暗碼：" in response.text
    assert 'id="labelCopyCount"' in response.text
    assert "Array.from({length:copies},()=>labelMarkup)" in response.text
    assert ".label:last-child{page-break-after:auto;break-after:auto}" in response.text
    assert "@media print" in response.text
    assert "本批可列印上限" in response.text
    assert 'id="chainLengthUnit"' in response.text
    assert 'id="editChainLengthUnit"' in response.text
    assert 'type="number" min="0" step="0.1"' in response.text
    assert "editChainLengthRaw" in response.text
    assert "/barcode.svg" in response.text
    assert 'class="barcode"' in response.text
    assert "data-print-product-label" in response.text
    assert 'id="companySelect"' in response.text
    assert 'id="inventoryStockPanel"' in response.text
    assert 'id="stocktakePanel"' in response.text
    assert 'id="stocktakeLocation"' in response.text
    assert 'id="stocktakeBarcode"' in response.text
    assert 'id="scanStocktakeButton"' in response.text
    assert 'id="applyStocktake"' in response.text
    assert "persistStocktakeDraft" in response.text
    assert "function newStocktakeAdjustmentKey()" in response.text
    assert "idempotency_key:x.idempotency_key" in response.text
    assert "idempotency_key:line.idempotency_key" in response.text
    assert "expected_net_weight:x.expected_net_weight" in response.text
    assert "expected_net_weight:Number(line.expected_net_weight??product.net_weight)||0" in response.text
    assert "/inventory/stocktake-adjustments" in response.text
    assert "expected_quantity:String(line.expected)" in response.text
    assert "actual_quantity:String(line.counted)" in response.text
    assert "盤點期間的庫存或商品淨重已改變，整批未入帳" in response.text
    assert "loadStocktakeBaseline(true)" in response.text
    assert 'id="inventoryAdjustmentForm"' in response.text
    assert 'id="inventoryTransferForm"' in response.text
    assert 'id="inventoryMovementPanel"' in response.text
    assert 'id="goldPricePanel"' in response.text
    assert 'id="goldPriceForm"' in response.text
    assert 'id="goldPriceScope"' in response.text
    assert 'id="salesPanel"' in response.text
    assert 'id="saleHeaderForm"' in response.text
    assert 'id="saleCartList"' in response.text
    assert 'id="saleBarcodeScan"' in response.text
    assert 'id="scanInventoryButton"' in response.text
    assert 'id="scanSaleButton"' in response.text
    assert 'id="scanProductButton"' in response.text
    assert 'id="scanModal"' in response.text
    assert "BarcodeDetector" in response.text
    assert '$("labelLotSelect").focus()' in response.text
    assert 'if(event.key==="Escape"){event.preventDefault();closeLabelLotModal();return;}' in response.text
    assert "function closeLabelLotModal()" in response.text
    assert 'class="label-lot-dialog" tabindex="-1"' in response.text
    assert 'event.key!=="Tab"' in response.text
    assert "dialog.querySelectorAll(" in response.text
    assert "last.focus()" in response.text and "first.focus()" in response.text
    assert "if(trigger&&trigger.isConnected)trigger.focus()" in response.text
    assert 'if(event.key==="Escape"){event.preventDefault();closeCameraScanner();return;}' in response.text
    assert 'class="scan-dialog" tabindex="-1"' in response.text
    assert "let scanTrigger=null" in response.text
    assert 'if(trigger&&trigger.isConnected)trigger.focus()' in response.text
    assert 'event.key!=="Tab"' in response.text
    assert 'dialog.querySelectorAll(\'button:not([disabled]),input:not([disabled]),select:not([disabled]),textarea:not([disabled]),a[href],[tabindex]:not([tabindex="-1"])\')' in response.text
    assert "last.focus()" in response.text and "first.focus()" in response.text
    assert '$("closeScanner").focus()' in response.text
    assert "button:focus-visible,a:focus-visible,input:focus-visible,select:focus-visible,textarea:focus-visible" in response.text
    assert "outline:3px solid #789b83;outline-offset:2px" in response.text
    assert 'id="completeSale"' in response.text
    assert 'id="voidSale"' in response.text
    assert 'id="newSale"' in response.text
    assert 'id="salePaymentPanel"' in response.text
    assert 'id="salePaymentForm"' in response.text
    assert 'id="actualPaymentMethod"' in response.text
    assert 'id="salePaymentList"' in response.text
    assert "function updateSalePaymentAmountForTender()" in response.text
    assert 'const settlementLabel=Number(sale.final_amount)<0?"本店應付客人":"顧客應付總額"' in response.text
    assert "本項結算：" in response.text
    assert 'direction===\"OUT\"?\"本店付款／退款\"' in response.text
    assert "刷卡（含 5% 手續費）" in response.text
    assert "現金（不加價）" in response.text
    assert "刷卡應收（含 5% 手續費）" in response.text
    assert 'id="supplierPayablesPanel"' in response.text
    assert 'id="purchasingPanel"' in response.text
    assert 'id="purchaseHeaderForm"' in response.text
    assert 'id="purchaseReceiveForm"' in response.text
    assert "function purchaseReceiveStorageKey(purchaseId,lineId)" in response.text
    assert "function readPendingPurchaseReceive(purchaseId,lineId)" in response.text
    assert "existing.fingerprint!==fingerprint" in response.text
    assert "payload.idempotency_key=pending.idempotency_key" in response.text
    assert "clearPendingPurchaseReceive" in response.text
    assert "已恢復上一筆尚未確認回應的到貨驗收" in response.text
    assert 'id="adjustmentScanCode"' in response.text
    assert 'id="transferScanCode"' in response.text
    assert 'id="purchaseScanCode"' in response.text
    assert 'id="purchaseReceiveScanCode"' in response.text
    assert 'id="scanPurchaseReceiveButton"' in response.text
    assert 'id="operatingExpensesPanel"' in response.text
    assert 'id="expenseForm"' in response.text
    assert 'id="restorePendingExpense"' in response.text
    assert "function pendingExpenseStorageKey(company,site)" in response.text
    assert "function readPendingExpense(company,site)" in response.text
    assert "savePendingExpense(companyId,selectedSiteId,payload)" in response.text
    assert "restorePendingExpenseDraft" in response.text
    assert "function savePendingExpensePayment(company,site,expense,paymentMethod)" in response.text
    assert "readPendingExpensePayment(companyId,selectedSiteId,row.id)" in response.text
    assert "clearPendingExpensePayment(companyId,selectedSiteId,expenseId)" in response.text
    assert "恢復尚未確認的費用" in response.text
    assert "恢復待確認付款" in response.text
    assert 'id="cashDrawerPanel"' in response.text
    assert 'id="cashDrawerForm"' in response.text
    assert 'id="restorePendingCashDrawer"' in response.text
    assert "function cashDrawerPendingStorageKey(company,site)" in response.text
    assert "function readPendingCashDrawerMovement(company,site)" in response.text
    assert "savePendingCashDrawerMovement(companyId,selectedSiteId,payload)" in response.text
    assert "payload.idempotency_key=pending.idempotency_key" in response.text
    assert "clearPendingCashDrawerMovement(companyId,selectedSiteId)" in response.text
    assert "恢復尚未確認的現金櫃異動" in response.text
    assert 'id="supplierForm"' in response.text
    assert 'id="supplierBillForm"' in response.text
    assert 'id="supplierPaymentForm"' in response.text
    assert "function supplierPaymentPendingStorageKey(company,site,bill)" in response.text
    assert "function readPendingSupplierPayment(company,site,bill)" in response.text
    assert "existing.fingerprint!==fingerprint" in response.text
    assert "savePendingSupplierPayment(companyId,selectedSiteId,selectedSupplierBill.id,payload)" in response.text
    assert "readPendingSupplierPayment(companyId,selectedSiteId,row.id)" in response.text
    assert "恢復待確認付款" in response.text
    assert "localStorage.setItem(key,JSON.stringify(pending))" in response.text
    assert "clearPendingSupplierPayment(companyId,selectedSiteId,selectedSupplierBill.id)" in response.text
    assert "已恢復上一筆尚未確認回應的付款" in response.text
    assert "重試時必須使用原付款單號" in response.text
    assert 'id="salesHistoryPanel"' in response.text
    assert 'id="salesHistoryQuery"' in response.text
    assert 'id="salesHistoryState"' in response.text
    assert 'id="salesHistoryList"' in response.text
    assert 'id="searchSalesHistory"' in response.text
    assert 'id="saleReturnPanel"' in response.text
    assert 'id="saleReturnForm"' in response.text
    assert 'id="returnPaymentForm"' in response.text
    assert 'id="dailyClosingForm"' in response.text
    assert 'id="cashCountCreateForm"' in response.text
    assert 'id="cashCountReviewForm"' in response.text
    assert 'id="productEditForm"' in response.text
    assert 'data-edit-product="' in response.text

    assert "帳面庫存商品" in response.text
    assert 'data-stocktake-verified="' in response.text
    assert "尚有" in response.text and "件商品未核對" in response.text
    assert "verified:!!x.verified" in response.text
    assert "已載入帳面庫存清單" in response.text

    assert 'id="quoteWorkbenchPanel"' in response.text
    assert "選擇正式商品" in response.text
    assert "臨時估價／修改報價規格" in response.text
    assert 'id="quoteProductCode"' in response.text
    assert 'id="quoteScanButton"' in response.text
    assert 'id="quoteProductSearch"' in response.text
    assert 'id="quoteSearchResults"' in response.text
    assert 'id="quoteProduct"' in response.text
    assert 'id="quoteManualName"' in response.text
    assert 'id="quoteManualSize"' in response.text
    assert 'id="quoteWeight"' in response.text
    assert 'id="quoteWeightUnit"' in response.text
    assert 'id="quoteLaborFee"' in response.text
    assert 'id="quoteHasTradeIn"' in response.text
    assert 'id="quoteTradeInDetails"' in response.text
    assert 'id="quoteOldGoldWeight"' in response.text
    assert 'id="quoteTradeInSource"' in response.text
    assert 'id="quoteTradeInRatio"' in response.text
    assert 'id="quoteTradeInRatioField"' in response.text
    assert 'id="quoteEntryPreview"' in response.text
    assert "function quoteTradeInInput()" in response.text
    assert "function renderQuoteEntryPreview()" in response.text
    assert "async function addQuoteProduct()" in response.text
    assert 'quoteHasTradeIn' in response.text and 'quoteTradeInDetails' in response.text
    assert "本店舊金（100%，不扣重）" in response.text
    assert "外店舊金（預設95%，可調整）" in response.text
    assert "臨時估價即時試算" in response.text
    assert 'manualName||"臨時估價"' in response.text
    assert "可留空，直接輸入重量與工錢估價" in response.text
    assert 'if(!product&&!name)' not in response.text
    assert "已勾選舊金折抵" in response.text
    assert 'id="quoteMixedTenderFields"' in response.text
    assert 'id="quoteCardAmount"' in response.text
    assert 'id="quoteCashAmount"' in response.text
    assert 'option value="MIXED">自訂刷卡＋現金' in response.text
    assert "function syncQuoteMixedTender(" in response.text
    assert "另一欄會自動補足" in response.text
    assert "刷卡部分加收 5%" in response.text
    assert 'id="quoteTransferToSaleButton"' in response.text
    assert "function transferQuoteToSale()" in response.text
    assert "source_location_id:null" in response.text
    assert "臨時估價／不扣庫存" in response.text
    assert "已將共用報價明細帶入銷售購物車" in response.text
    assert "無現貨／需訂製：建立客戶訂購單" in response.text
    assert 'id="quoteOrderCustomerName"' in response.text
    assert 'id="quoteOrderDeposit"' in response.text
    assert "建立客訂單並收訂金" in response.text
    assert "let pendingCustomerOrderCreate=null" in response.text
    assert "function newCustomerOrderIdempotencyKey()" in response.text
    assert "pendingCustomerOrderCreate.fingerprint!==fingerprint" in response.text
    assert "idempotency_key:pendingCustomerOrderCreate.idempotency_key" in response.text
    assert "finally{button.disabled=false;}" in response.text
    assert 'order_no:"CO-"+Date.now().toString()' in response.text
    assert "訂單不扣庫存" in response.text
    assert "折抵後應付商品金額" in response.text
    assert "客戶折抵合計" in response.text
    assert 'function updateQuoteTradeInRatioVisibility()' in response.text
    assert 'field.classList.toggle("hidden",$("quoteTradeInSource").value!=="EXTERNAL")' in response.text
    assert 'id="saleOldGoldWeight"' in response.text


def test_compact_phone_layout_stacks_form_fields_without_narrowing_specialized_controls():
    response = TestClient(app).get("/app")
    assert response.status_code == 200
    assert "@media(max-width:380px)" in response.text
    assert ".grid:not(.gold-price-entry-grid){grid-template-columns:minmax(0,1fr);gap:8px}" in response.text
    # Keep deliberately paired controls, such as gold-price entry, in two columns.
    assert ".gold-price-entry-grid{grid-template-columns:1fr 1fr" in response.text
    assert ".scan-settings{display:grid;grid-template-columns:1fr 1fr" in response.text


def test_inventory_stock_cards_separate_quantity_and_product_trace_details():
    response = TestClient(app).get("/app")
    assert response.status_code == 200
    assert 'class="item stock-item"' in response.text
    assert 'class="stock-item-head"' in response.text
    assert 'class="stock-item-quantity"' in response.text
    assert 'class="stock-item-meta"' in response.text
    assert '<small>目前庫存</small>' not in response.text
    assert '<span>目前庫存</span>' in response.text
    assert '<small>儲存位置</small>' in response.text
    assert '<small>條碼</small>' in response.text
    assert 'max-width:380px' in response.text
    assert 'grid-template-columns:minmax(0,1fr)' in response.text
    # The stock-card renderer escapes all dynamic product and stock values.
    assert 'escapeHtml(x.product_name)' in response.text
    assert 'escapeHtml(x.product_code)' in response.text
    assert 'escapeHtml(x.quantity)' in response.text
    assert 'escapeHtml(x.barcode||"未設定")' in response.text


def test_category_shortcuts_remove_expand_state_and_normalize_subnavigation_labels():
    response = TestClient(app).get("/app")
    assert response.status_code == 200
    assert r'replace(/\s*(展開|收合)\s*$/,"")' in response.text
    assert r'replace(/\s+/g," ")' in response.text
    assert r'replace(/\\s*(展開|收合)\\s*$/,"")' not in response.text
    assert r'replace(/\\s+/g," ")' not in response.text


def test_product_master_cards_prioritize_identity_and_group_specifications():
    response = TestClient(app).get("/app")
    assert response.status_code == 200
    assert 'class="item product-item"' in response.text
    assert 'class="product-results-count"' in response.text
    assert 'class="product-item-identity"' in response.text
    assert 'class="product-item-meta"' in response.text
    assert 'class="product-item-specs"' in response.text
    assert '<small>條碼</small>' in response.text
    assert '<small>商品分類</small>' in response.text
    assert '<small>預設銷售工錢</small>' in response.text
    assert 'max-width:380px' in response.text
    # Preserve escaping for product names, codes, weights, fees, and action IDs.
    assert 'escapeHtml(x.name)' in response.text
    assert 'escapeHtml(x.product_code)' in response.text
    assert 'escapeHtml(x.gross_weight)' in response.text
    assert 'escapeHtml(x.net_weight)' in response.text
    assert 'escapeHtml(x.labor_fee)' in response.text
    assert 'data-edit-product="' in response.text
    assert 'data-print-product-label="' in response.text
    assert 'escapeHtml(x.id)' in response.text


def test_purchasing_and_sales_cards_share_clear_mobile_transaction_hierarchy():
    response = TestClient(app).get("/app")
    assert response.status_code == 200
    for class_name in (
        "transaction-item",
        "purchase-line-item",
        "purchase-order-item",
        "sale-line-item",
        "sales-history-item",
        "transaction-item-head",
        "transaction-item-primary",
        "transaction-item-meta",
        "transaction-item-lines",
        "transaction-item-actions",
    ):
        assert f'class="' in response.text and class_name in response.text
    assert '<small>訂購數量</small>' in response.text
    assert '<small>已驗收／訂購</small>' in response.text
    assert '<small>商品驗收進度（已收／訂購）</small>' in response.text
    assert 'Number(row.final_amount)<0?"本店應付":"應收金額"' in response.text
    assert 'max-width:380px' in response.text
    # Existing business fields and action identifiers remain escaped and wired.
    for expression in (
        "escapeHtml(line.product.product_code)",
        "escapeHtml(line.product.name)",
        "escapeHtml(line.quantity)",
        "escapeHtml(line.unit_cost)",
        "escapeHtml(line.cost_labor_fee)",
        "escapeHtml(line.product.barcode||\"未設定\")",
        "escapeHtml(line.old_gold_weight)",
        "escapeHtml(row.purchase_no)",
        "escapeHtml(row.id)",
        "escapeHtml(row.sale_no)",
    ):
        assert expression in response.text
    assert 'data-remove-purchase-line="' in response.text
    assert 'data-remove-sale-line="' in response.text
    assert 'data-submit-purchase="' in response.text
    assert 'data-cancel-purchase="' in response.text
    assert 'data-open-receive="' in response.text
    assert 'data-open-sale="' in response.text


def test_receiving_and_settlement_cards_highlight_remaining_and_payment_details():
    response = TestClient(app).get("/app")
    assert response.status_code == 200
    for class_name in (
        "receive-line-item",
        "receive-remaining",
        "settlement-summary",
        "settlement-summary-head",
        "settlement-summary-meta",
        "settlement-summary-breakdown",
        "settlement-outstanding",
        "settlement-entry",
        "settlement-entry-head",
        "settlement-entry-amount",
        "settlement-entry-meta",
        "settlement-entry-note",
        "return-history-item",
    ):
        assert class_name in response.text
    assert '<small>尚餘待驗收</small>' in response.text
    assert '<small>已驗收數量</small>' in response.text
    assert '<small>訂購總數量</small>' in response.text
    assert 'data-receive-line="' in response.text
    assert 'data-remaining="' in response.text
    assert 'data-select-return="' in response.text
    assert '交易編號' in response.text
    assert '登錄時間' in response.text
    # Keep settlement and return values escaped before inserting into HTML.
    for expression in (
        "escapeHtml(obligation.toFixed(2))",
        "escapeHtml(paid.toFixed(2))",
        "escapeHtml(remaining.toFixed(2))",
        "escapeHtml(Number(row.amount).toFixed(2))",
        "escapeHtml(row.reference_no)",
        "escapeHtml(row.return_no)",
        "escapeHtml(row.id)",
    ):
        assert expression in response.text


def test_quote_workbench_groups_steps_without_changing_quote_controls():
    response = TestClient(app).get("/app")
    assert response.status_code == 200
    html = response.text
    for class_name in (
        "quote-step-card",
        "quote-catalog-card",
        "quote-manual-card",
        "quote-tradein-card",
        "quote-cart-card",
        "quote-step-heading",
        "quote-live-preview",
        "quote-total-summary",
        "quote-primary-actions",
        "quote-manual-grid",
    ):
        assert class_name in html
    for element_id in (
        "quoteProductCode",
        "quoteScanButton",
        "quoteProductSearch",
        "quoteSearchResults",
        "quoteProduct",
        "quoteManualName",
        "quoteManualSize",
        "quoteWeight",
        "quoteWeightUnit",
        "quoteLaborFee",
        "quoteHasTradeIn",
        "quoteOldGoldWeight",
        "quoteTradeInSource",
        "quoteTradeInRatio",
        "quoteAddProductButton",
        "quoteEntryPreview",
        "quoteLines",
        "quotePaymentMethod",
        "quoteCardAmount",
        "quoteCashAmount",
        "quoteCalcSummary",
        "quoteTransferToSaleButton",
    ):
        assert html.count(f'id="{element_id}"') == 1
    # The existing quote calculation and trade-in logic remain in place.
    for logic in (
        "function quoteCalculateLineAmount(",
        "function renderQuoteEntryPreview(",
        "function renderQuoteCalculation(",
        "function addQuoteProduct(",
        "function transferQuoteToSale(",
        'tradeInSource==="LOCAL"?1:tradeInRatio',
        'cardAmount*0.05',
        "loadQuoteStockBalances()",
    ):
        assert logic in html
    assert "@media(max-width:760px)" in html
    assert "@media(max-width:380px)" in html


def test_product_create_and_edit_forms_are_grouped_without_changing_fields():
    response = TestClient(app).get("/app")
    assert response.status_code == 200
    html = response.text
    assert html.count('id="productForm"') == 1
    assert html.count('id="productEditForm"') == 1
    assert html.count("product-form-section") >= 8
    assert "商品識別" in html
    assert "商品分類與材質" in html
    assert "重量與工錢" in html
    assert "商品規格與備註" in html
    create_ids = (
        "productPrefix", "productCode", "generateCode", "barcode", "productName",
        "productCategory", "materialCode", "grossWeight", "netWeight", "weightUnit",
        "laborFee", "chainLength", "chainLengthUnit", "styleCode", "productNote",
    )
    edit_ids = (
        "editProductId", "editChainLengthRaw", "editProductCode", "editBarcode",
        "editProductName", "editProductCategory", "editMaterialCode",
        "editGrossWeight", "editNetWeight", "editWeightUnit", "editLaborFee",
        "editChainLength", "editChainLengthUnit", "editStyleCode", "editProductNote",
        "cancelProductEdit",
    )
    for element_id in create_ids + edit_ids:
        assert html.count(f'id="{element_id}"') == 1
    assert 'type="submit">新增商品</button>' in html
    assert 'type="submit">儲存修改</button>' in html
    assert "product-form-actions" in html
    assert "product-form-section" in html
    assert "@media(max-width:760px)" in html
    assert "@media(max-width:380px)" in html


def test_global_status_feedback_and_button_states_are_consistent():
    response = TestClient(app).get("/app")
    assert response.status_code == 200
    html = response.text
    assert ".status.success{color:#28724d;font-weight:700}" in html
    assert ".status.error{color:#b42318;font-weight:700}" in html
    assert 'el.classList.toggle("success",!error&&success)' in html
    assert 'el.classList.remove("error","success")' in html
    assert "const success=/成功|已建立|已儲存" in html
    assert "button:not(:disabled):hover" in html
    assert "button:not(:disabled):active" in html
    assert "button:disabled{opacity:.48;cursor:not-allowed;filter:none;transform:none;box-shadow:none}" in html
    assert "button.secondary:disabled{opacity:.42}" in html
    assert html.count(".status.success{") == 1
    assert html.count(".status.error{") == 1


def test_responsive_workspace_prevents_narrow_viewport_overflow():
    response = TestClient(app).get("/app")
    assert response.status_code == 200
    html = response.text
    assert '<meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">' in html
    assert "@media(max-width:520px)" in html
    assert "@media(max-width:380px)" in html
    assert "main>section.panel{min-width:0;max-width:100%}" in html
    assert ".toolbar{min-width:0;flex-wrap:wrap}" in html
    assert ".toolbar input{min-width:0;flex:1 1 180px}" in html
    assert ".actions button{min-width:0;max-width:100%}" in html
    assert "#quoteWorkbenchPanel .quote-product-result>span:first-child{min-width:0;flex:1 1 auto;overflow-wrap:anywhere}" in html
    assert "#quoteWorkbenchPanel .quote-product-result .quote-stock{flex:0 1 auto;min-width:0;max-width:38%;overflow-wrap:anywhere}" in html
    assert "#quoteWorkbenchPanel .quote-product-result{flex-direction:column;gap:7px}" in html
    assert ".panel-subnav" in html and ".quick-nav" in html and ".category-nav" in html



def test_bank_and_gold_material_workspaces_are_served():
    client = TestClient(app)

    banking = client.get("/banking")
    assert banking.status_code == 200
    assert "銀行帳戶與對帳" in banking.text
    assert 'id="accountForm"' in banking.text
    assert 'id="importForm"' in banking.text
    assert "/statement-imports" in banking.text
    assert "/reconciliation-snapshots" in banking.text
    assert "/reconciliation-report" in banking.text
    assert '"/export.csv"' in banking.text

    gold_material = client.get("/gold-material")
    assert gold_material.status_code == 200
    assert "金料往來管理" in gold_material.text
    assert 'id="movementForm"' in gold_material.text
    assert 'id="allocationPanel"' in gold_material.text
    assert "/gold-material/balance" in gold_material.text
    assert "/supplier-payables/bills" in gold_material.text



def test_sale_and_return_payment_forms_use_retry_safe_idempotency_keys():
    response = TestClient(app).get("/app")
    assert response.status_code == 200
    html = response.text
    assert "function getPaymentIdempotencyKey" in html
    assert "function clearPaymentIdempotencyKey" in html
    assert 'payload.idempotency_key=idempotencyKey' in html
    assert 'getPaymentIdempotencyKey("sale",currentSale.id,payload)' in html
    assert 'getPaymentIdempotencyKey("return",selectedReturn.id,payload)' in html
    assert html.count('if(idempotencyKey&&error.status===422)') == 2
    assert 'error.status>=400&&error.status<500' not in html



def test_banking_workspace_exposes_pending_transfer_link_controls():
    response = TestClient(app).get("/banking")
    assert response.status_code == 200
    html = response.text
    assert 'id="pendingTransferPanel"' in html
    assert 'id="pendingTransferList"' in html
    assert 'id="transferLinkActor"' in html
    assert "/bank-accounts/pending-transfers" in html
    assert "/transfer-links" in html
    assert "opening_balance_at" in html or "期初餘額日期" in html
