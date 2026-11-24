import assert from "node:assert/strict";
import fs from "node:fs";
import test from "node:test";

const html = fs.readFileSync("app/static/index.html", "utf8");

test("inventory stock cards render localized weight units", () => {
  assert.match(
    html,
    /escapeHtml\(product\.net_weight\)\s*\+\s*' '\s*\+\s*escapeHtml\(goldUnitLabel\(product\.weight_unit_code\s*\|\|\s*"QIAN"\)\)/
  );
  assert.doesNotMatch(html, /escapeHtml\(product\.weight_unit_code\)/);
});

test("product cards render localized weight units", () => {
  assert.match(
    html,
    /escapeHtml\(x\.gross_weight\)\s*\+\s*'／'\s*\+\s*escapeHtml\(x\.net_weight\)\s*\+\s*' '\s*\+\s*escapeHtml\(goldUnitLabel\(x\.weight_unit_code\s*\|\|\s*"QIAN"\)\)/
  );
  assert.doesNotMatch(html, /escapeHtml\(x\.weight_unit_code\)/);
});
