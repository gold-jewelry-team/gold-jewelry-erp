import assert from "node:assert/strict";
import fs from "node:fs";
import test from "node:test";

const html = fs.readFileSync("app/static/index.html", "utf8");

test("inventory operation recovery inbox is available in the movement workspace", () => {
  assert.match(html, /id="inventoryOperationRequestList"/);
  assert.match(html, /id="refreshInventoryOperationRequests"/);
  assert.match(html, /\/inventory\/operation-requests\?/);
  assert.match(html, /async function loadInventoryOperationRequests\(\)/);
  assert.match(html, /PENDING:"待核對"/);
  assert.match(html, /FAILED:"曾失敗"/);
});

test("recovery action requires confirmation and sends no replacement payload", () => {
  assert.match(html, /data-operation-retry=/);
  assert.match(html, /confirm\("請先確認這筆原操作的商品、位置與數量/);
  assert.match(
    html,
    /\/operation-requests\/"\+requestId\+"\/retry",\{method:"POST"\}/,
  );
  assert.match(html, /只會使用原始保存內容/);
});
