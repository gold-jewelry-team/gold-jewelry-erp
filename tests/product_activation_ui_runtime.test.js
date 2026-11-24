import assert from "node:assert/strict";
import fs from "node:fs";
import test from "node:test";

const html = fs.readFileSync("app/static/index.html", "utf8");

test("product list supports inactive visibility and status actions", () => {
  assert.match(html, /productIncludeInactive/);
  assert.match(html, /include_inactive/);
  assert.match(html, /data-toggle-product=/);
  assert.match(html, /重新啟用/);
  assert.match(html, /商品已停用/);
  assert.match(html, /商品已重新啟用/);
});

test("inactive products cannot be printed from the ordinary product list", () => {
  assert.match(html, /x\.is_active\?'<button class="secondary" type="button" data-print-product-label=/);
  assert.match(html, /停用商品不會刪除庫存或歷史交易/);
});
