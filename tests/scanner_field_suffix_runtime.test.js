import assert from "node:assert/strict";
import fs from "node:fs";
import test from "node:test";

const html = fs.readFileSync("app/static/index.html", "utf8");

test("stocktake barcode field uses the shared Enter and Tab scanner handler", () => {
  assert.match(
    html,
    /\$\("stocktakeBarcode"\)\.addEventListener\("keydown",event=>\{handleKeyboardScannerInput\(event,\$\("stocktakeBarcode"\)\.value,code=>handleScannedProductCode\(code,"stocktake"\)\);\}\);/
  );
  assert.match(html, /掃描／輸入商品條碼（Enter／Tab）/);
});

test("quote product code field uses the shared Enter and Tab scanner handler", () => {
  assert.match(
    html,
    /\$\("quoteProductCode"\)\.addEventListener\("keydown",event=>\{\s*handleKeyboardScannerInput\(event,event\.target\.value,code=>handleScannedProductCode\(code,"quote"\)\);\s*\}\);/
  );
  assert.match(html, /按 Enter／Tab 查找/);
});

test("all keyboard scanner fields show consistent Enter and Tab guidance", () => {
  for (const id of [
    "saleBarcodeScan",
    "adjustmentScanCode",
    "transferScanCode",
    "purchaseScanCode",
    "purchaseReceiveScanCode",
  ]) {
    const field = html.match(new RegExp(`<input[^>]*id="${id}"[^>]*>`))?.[0];
    assert.ok(field, `missing scanner field: ${id}`);
    assert.match(field, /Enter／Tab/, `${id} should explain Enter and Tab suffixes`);
  }
  assert.match(html, /掃描／輸入商品條碼（Enter／Tab 加入）/);
});
