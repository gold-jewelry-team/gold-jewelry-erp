import assert from "node:assert/strict";
import fs from "node:fs";
import test from "node:test";

const html = fs.readFileSync("app/static/index.html", "utf8");
const marker = 'const rows=(order.items||[]).map(item=>';
const start = html.indexOf(marker);
const end = html.indexOf('.join("");', start);
assert.notEqual(start, -1, "Customer order print row renderer must exist");
assert.notEqual(end, -1, "Customer order print row renderer boundary must exist");
const source = html.slice(start, end);

test("customer order print uses Traditional Chinese weight units", () => {
  assert.match(source, /goldUnitLabel\(item\.weight_unit_code\s*\|\|\s*"QIAN"\)/);
  assert.doesNotMatch(source, /escapeHtml\(item\.weight_unit_code\)/);
});

test("customer order print keeps labor and amount columns", () => {
  assert.match(source, /escapeHtml\(item\.labor_fee\)/);
  assert.match(source, /quoteMoney\(item\.estimated_line_amount\s*\|\|\s*0\)/);
});
