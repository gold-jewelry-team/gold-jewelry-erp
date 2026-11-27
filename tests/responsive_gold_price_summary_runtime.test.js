import assert from "node:assert/strict";
import fs from "node:fs";
import test from "node:test";
import vm from "node:vm";

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
  const responsiveStart = html.indexOf("/* Responsive gold summary");
  const phoneStart = html.indexOf("@media(max-width:520px){", responsiveStart);
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

test("foreign-currency conversion stays hidden until its checkbox is selected", () => {
  assert.match(html, /<label class="gold-currency-toggle" for="showGoldCurrencyConversion">/);
  assert.match(html, /<input id="showGoldCurrencyConversion" type="checkbox" aria-controls="goldCurrencyRateEditor">/);
  assert.match(html, /id="goldCurrencyRateEditor" class="gold-currency-rate-editor hidden"/);
  assert.ok(html.includes('$("showGoldCurrencyConversion").addEventListener("change",event=>setGoldCurrencyConversionVisible(event.target.checked));'));
  assert.match(html, /function setGoldCurrencyConversionVisible\(visible\)/);
  assert.ok(
    html.indexOf('id="goldPriceReminder"') < html.indexOf('id="goldSummaryValues"'),
    "gold-price freshness reminder must appear before the price figures",
  );
});

const reminderStart = html.indexOf("function goldPriceReminderState(");
const reminderEnd = html.indexOf("function isGoldPriceReminderBusinessDay()", reminderStart);
assert.notEqual(reminderStart, -1, "gold-price reminder state helper must exist");
assert.notEqual(reminderEnd, -1, "gold-price reminder state helper must have a stable boundary");
const reminderContext = {};
vm.createContext(reminderContext);
vm.runInContext(html.slice(reminderStart, reminderEnd), reminderContext);

test("weekday with missing prices shows a prominent stale-price warning", () => {
  const state = reminderContext.goldPriceReminderState({
    today: "2026-11-27",
    buyDate: "2026-11-26",
    sellDate: null,
    isBusinessDay: true,
    latestDate: "2026-11-26",
  });
  assert.equal(state.kind, "warning");
  assert.match(state.text, /今日金價尚未完整更新/);
  assert.match(state.text, /賣出價/);
  assert.match(state.text, /最近一次有效牌價：2026-11-26/);
  assert.match(state.text, /目前顯示最近一次有效牌價/);
});

test("weekends and configured closure dates explain that prices may not update", () => {
  for (const isBusinessDay of [false]) {
    const state = reminderContext.goldPriceReminderState({
      today: "2026-11-28",
      buyDate: "2026-11-27",
      sellDate: "2026-11-27",
      isBusinessDay,
      latestDate: "2026-11-27",
    });
    assert.equal(state.kind, "closed");
    assert.match(state.text, /週末或已設定的休市日/);
    assert.match(state.text, /連續假日/);
    assert.doesNotMatch(state.text, /尚未完整更新/);
  }
});

test("fully updated prices show a positive state even on a closed day", () => {
  const state = reminderContext.goldPriceReminderState({
    today: "2026-11-28",
    buyDate: "2026-11-28",
    sellDate: "2026-11-28",
    isBusinessDay: false,
    latestDate: "2026-11-28",
  });
  assert.equal(state.kind, "success");
  assert.match(state.text, /今日買入價與賣出價均已更新/);
});

test("a business day with no saved prices clearly reports both missing price types", () => {
  const state = reminderContext.goldPriceReminderState({
    today: "2026-11-27",
    buyDate: null,
    sellDate: null,
    isBusinessDay: true,
    latestDate: null,
  });
  assert.equal(state.kind, "warning");
  assert.match(state.text, /買入價與賣出價/);
  assert.match(state.text, /目前尚無有效牌價紀錄/);
  assert.match(state.text, /請至「金價管理」確認是否已建立牌價/);
  assert.doesNotMatch(state.text, /目前顯示最近一次有效牌價/);
});
