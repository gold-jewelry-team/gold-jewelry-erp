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
