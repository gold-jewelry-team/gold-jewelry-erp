import assert from "node:assert/strict";
import fs from "node:fs";
import test from "node:test";

const html = fs.readFileSync("app/static/index.html", "utf8");

test("inventory movement history exposes record and idempotency identifiers", () => {
  const start = html.indexOf("async function loadInventoryMovements()");
  const end = html.indexOf("\nfunction taipeiDateTimeLocalValue()", start);
  assert.ok(start >= 0 && end > start, "movement history renderer must exist");
  const renderer = html.slice(start, end);
  assert.match(renderer, /異動紀錄 ID：/);
  assert.match(renderer, /x\.id\|\|"—"/);
  assert.match(renderer, /冪等識別碼：/);
  assert.match(renderer, /x\.reference_id\|\|"—"/);
  assert.match(renderer, /escapeHtml\(x\.id/);
  assert.match(renderer, /escapeHtml\(x\.reference_id/);
});

test("inventory adjustment and transfer warn against resubmitting unresolved operations", () => {
  assert.match(
    html,
    /暫存遺失且結果不明，先查詢下方異動紀錄，核對商品、位置、數量、時間與備註；確認前不要重新建立調整/,
  );
  assert.match(
    html,
    /暫存遺失且結果不明，先查詢下方異動紀錄，核對商品、來源／目的位置、數量、時間與備註；確認前不要重新建立調撥/,
  );
  assert.match(html, /不代表可在遺失後自動恢復原請求/);
});
