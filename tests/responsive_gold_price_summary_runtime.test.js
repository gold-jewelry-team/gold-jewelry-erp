import assert from "node:assert/strict";
import fs from "node:fs";
import test from "node:test";

const html = fs.readFileSync("app/static/index.html", "utf8");

test("current gold summary fills the available header width without a fixed narrow cap", () => {
  assert.match(html, /<section id="goldPriceSummary" class="gold-summary"/);
  assert.match(html, /#goldPriceSummary\{width:100%;max-width:1180px;min-width:0\}/);
  assert.match(html, /#goldPriceSummary \.gold-summary-values\{display:grid;grid-template-columns:repeat\(2,minmax\(0,1fr\)\)/);
  assert.match(html, /#goldPriceSummary \.gold-summary-price\{min-width:0;flex-wrap:wrap/);
});

test("tablet gold summary uses full available width and tablet header gutters", () => {
  assert.match(html, /@media\(min-width:640px\) and \(max-width:899px\)\{\s*header\{padding-left:20px;padding-right:20px\}\s*#goldPriceSummary\{max-width:none\}/);
  assert.match(html, /#goldPriceSummary \.gold-currency-values\{grid-template-columns:repeat\(2,minmax\(0,1fr\)\)\}/);
});

test("narrow phones stack prices and currency inputs while keeping copy actions usable", () => {
  const phoneStart = html.lastIndexOf("@media(max-width:520px){");
  assert.notEqual(phoneStart, -1, "missing narrow-phone responsive rules");
  const phoneEnd = html.indexOf("\n}", phoneStart);
  assert.notEqual(phoneEnd, -1, "narrow-phone responsive rules are not closed");
  const phone = html.slice(phoneStart, phoneEnd);
  assert.match(phone, /#goldPriceSummary \.gold-summary-values\{grid-template-columns:minmax\(0,1fr\)\}/);
  assert.match(phone, /#goldPriceSummary \.gold-currency-rate-fields\{grid-template-columns:minmax\(0,1fr\)\}/);
  assert.match(phone, /#goldPriceSummary \.gold-currency-values\{grid-template-columns:minmax\(0,1fr\)\}/);
  assert.match(phone, /#goldPriceSummary \.gold-summary-actions\{display:grid;grid-template-columns:repeat\(2,minmax\(0,1fr\)\)\}/);
});

test("very narrow phones stack copy buttons and keep select controls within the viewport", () => {
  assert.match(html, /@media\(max-width:360px\)\{\s*#goldPriceSummary \.gold-summary-head select\{flex:1 1 100%;width:100%\}\s*#goldPriceSummary \.gold-summary-actions\{grid-template-columns:minmax\(0,1fr\)\}/);
});

test("desktop gold summary retains a wide but controlled price layout", () => {
  assert.match(html, /@media\(min-width:900px\)\{\s*#goldPriceSummary\{max-width:1180px\}\s*#goldPriceSummary \.gold-summary-values\{grid-template-columns:repeat\(2,minmax\(220px,1fr\)\);max-width:620px\}/);
});
