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
  assert.match(state.text, /今日買進價與賣出價均已更新/);
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
  assert.match(state.text, /買進價與賣出價/);
  assert.match(state.text, /目前尚無有效牌價紀錄/);
  assert.match(state.text, /請至「金價管理」確認是否已建立牌價/);
  assert.doesNotMatch(state.text, /目前顯示最近一次有效牌價/);
});

test("gold summary keeps the currency unit phrase together while allowing the trend hint to wrap", () => {
  assert.ok(html.includes(`<span class="gold-price-unit">／每'+unitName+'</span>`));
  assert.match(html, /#goldPriceSummary \.gold-price-unit\{white-space:nowrap;display:inline-block\}/);
  assert.ok(html.includes(`class="gold-price-unit">／每'+unitName+'</span>'+trendHtml`));
});

test("gold summary renders daily movement hints only beside the home buy and sell prices", () => {
  assert.match(html, /function getGoldPriceDailyComparison\(current,history,displayUnit\)/);
  assert.match(html, /renderPrice\(buy,"買進價",true\)\+renderPrice\(sell,"賣出價",true\)/);
  assert.match(html, /gold-price-trend-icon/);
  assert.match(html, /is-up/);
  assert.match(html, /is-down/);
  assert.match(html, /is-same/);
  assert.match(html, /goldPriceHistoryRows=Array\.isArray\(history\)\?history:\[\]/);
});

const comparisonStart = html.indexOf("function getGoldPriceDailyComparison(");
const comparisonEnd = html.indexOf("function renderGoldPriceViews()", comparisonStart);
assert.notEqual(comparisonStart, -1, "daily gold comparison helper must exist");
assert.notEqual(comparisonEnd, -1, "daily gold comparison helper must have a stable boundary");
const comparisonContext = {
  taipeiDateKey(value) {
    if (!value) return "";
    const date = value instanceof Date ? value : new Date(value);
    if (Number.isNaN(date.getTime())) return "";
    return new Intl.DateTimeFormat("en-CA", {
      timeZone: "Asia/Taipei",
      year: "numeric",
      month: "2-digit",
      day: "2-digit",
    }).format(date);
  },
  convertGoldPrice(value, fromUnit, toUnit) {
    const grams = { QIAN: 3.75, GRAM: 1, TAEL: 37.5 };
    const amount = Number(value);
    if (!grams[fromUnit] || !grams[toUnit] || !Number.isFinite(amount)) return null;
    return amount * grams[toUnit] / grams[fromUnit];
  },
};
vm.createContext(comparisonContext);
vm.runInContext(html.slice(comparisonStart, comparisonEnd), comparisonContext);

test("gold price comparison marks an increase against the previous available price date", () => {
  const current = {
    price_type: "BUY", price_value: "13000", currency_code: "TWD",
    unit_code: "QIAN", site_id: null, effective_at: "2026-11-27T10:00:00+08:00",
  };
  const history = [
    { ...current, price_value: "12900", effective_at: "2026-11-27T09:00:00+08:00" },
    { ...current, price_value: "12500", effective_at: "2026-11-26T10:00:00+08:00" },
    { ...current, price_value: "12400", effective_at: "2026-11-25T10:00:00+08:00" },
  ];
  const result = comparisonContext.getGoldPriceDailyComparison(current, history, "QIAN");
  assert.equal(result.direction, "up");
  assert.equal(result.delta, 500);
  assert.equal(result.previousDate, "2026-11-26");
});

test("gold price comparison marks a decrease and an unchanged price", () => {
  const base = {
    price_type: "SELL", currency_code: "TWD", unit_code: "QIAN",
    site_id: null, effective_at: "2026-11-27T10:00:00+08:00",
  };
  const lower = comparisonContext.getGoldPriceDailyComparison(
    { ...base, price_value: "12800" },
    [{ ...base, price_value: "13000", effective_at: "2026-11-26T10:00:00+08:00" }],
    "QIAN",
  );
  assert.equal(lower.direction, "down");
  assert.equal(lower.delta, -200);

  const same = comparisonContext.getGoldPriceDailyComparison(
    { ...base, price_value: "13000" },
    [{ ...base, price_value: "13000", effective_at: "2026-11-26T10:00:00+08:00" }],
    "QIAN",
  );
  assert.equal(same.direction, "same");
  assert.equal(same.delta, 0);
});

test("daily comparison converts different gold weight units before comparing", () => {
  const current = {
    price_type: "BUY", price_value: "13000", currency_code: "TWD",
    unit_code: "QIAN", site_id: null, effective_at: "2026-11-27T10:00:00+08:00",
  };
  const previous = {
    ...current, price_value: "3300", unit_code: "GRAM",
    effective_at: "2026-11-26T10:00:00+08:00",
  };
  const result = comparisonContext.getGoldPriceDailyComparison(current, [previous], "QIAN");
  assert.equal(result.direction, "up");
  assert.equal(result.delta, 625);
});

test("site-specific price history takes precedence over newer company fallback rows", () => {
  const current = {
    price_type: "BUY", price_value: "14500", currency_code: "TWD",
    unit_code: "QIAN", site_id: "site-1", effective_at: "2026-11-27T10:00:00+08:00",
  };
  const history = [
    { ...current, site_id: null, price_value: "15500", effective_at: "2026-11-26T10:00:00+08:00" },
    { ...current, price_value: "14000", effective_at: "2026-11-25T10:00:00+08:00" },
  ];
  const result = comparisonContext.getGoldPriceDailyComparison(current, history, "QIAN");
  assert.equal(result.previousDate, "2026-11-25");
  assert.equal(result.delta, 500);
});

test("daily comparison falls back to company history when a site has no earlier site quote", () => {
  const current = {
    price_type: "SELL", price_value: "16000", currency_code: "TWD",
    unit_code: "QIAN", site_id: "site-1", effective_at: "2026-11-27T10:00:00+08:00",
  };
  const previous = {
    ...current, site_id: null, price_value: "15800",
    effective_at: "2026-11-26T10:00:00+08:00",
  };
  const result = comparisonContext.getGoldPriceDailyComparison(current, [previous], "QIAN");
  assert.equal(result.previousDate, "2026-11-26");
  assert.equal(result.direction, "up");
  assert.equal(result.delta, 200);
});

test("daily comparison hides when no previous day or safe currency/unit comparison exists", () => {
  const current = {
    price_type: "BUY", price_value: "13000", currency_code: "TWD",
    unit_code: "QIAN", site_id: null, effective_at: "2026-11-27T10:00:00+08:00",
  };
  assert.equal(comparisonContext.getGoldPriceDailyComparison(current, [], "QIAN"), null);
  assert.equal(comparisonContext.getGoldPriceDailyComparison(
    current,
    [{ ...current, price_value: "12900", effective_at: "2026-11-27T09:00:00+08:00" }],
    "QIAN",
  ), null);
  assert.equal(comparisonContext.getGoldPriceDailyComparison(
    current,
    [{ ...current, currency_code: "USD", price_value: "400", effective_at: "2026-11-26T09:00:00+08:00" }],
    "QIAN",
  ), null);
  assert.equal(comparisonContext.getGoldPriceDailyComparison(
    current,
    [{ ...current, unit_code: "UNKNOWN", price_value: "400", effective_at: "2026-11-26T09:00:00+08:00" }],
    "QIAN",
  ), null);
});
