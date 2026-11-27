import assert from "node:assert/strict";
import fs from "node:fs";
import test from "node:test";
import vm from "node:vm";

const html = fs.readFileSync("app/static/index.html", "utf8");
const start = html.indexOf("function stocktakeBunnyFeedbackState({");
const end = html.indexOf("\nfunction renderStocktake()", start);
assert.notEqual(start, -1, "Stocktake rabbit feedback state helper must exist");
assert.notEqual(end, -1, "Stocktake rabbit feedback helper must have a stable boundary");
const source = html.slice(start, end);

function getState(overrides = {}) {
  const defaults = {
    locationSelected: true,
    hasLines: true,
    pendingCount: 3,
    verifiedCount: 1,
    varianceCount: 0,
    appliedCount: 0,
  };
  const context = {};
  vm.createContext(context);
  vm.runInContext(source, context);
  return context.stocktakeBunnyFeedbackState({ ...defaults, ...overrides });
}

test("unverified stocktake items show a clear pending-review warning", () => {
  const state = getState({ pendingCount: 4, verifiedCount: 1 });
  assert.equal(state.title, "盤點待核對");
  assert.equal(state.variant, "is-alert");
  assert.match(state.copy, /尚有 3 項商品未完成核對/);
  assert.match(state.copy, /再執行整批入帳/);
});

test("unverified items and already-confirmed variances are both disclosed", () => {
  const state = getState({ pendingCount: 4, verifiedCount: 2, varianceCount: 1 });
  assert.equal(state.title, "盤點待核對");
  assert.equal(state.variant, "is-alert");
  assert.match(state.copy, /尚有 2 項商品待勾選核對/);
  assert.match(state.copy, /另有 1 項數量有差異/);
});

test("verified quantity differences remain a warning until inventory posting", () => {
  const state = getState({ pendingCount: 3, verifiedCount: 3, varianceCount: 2 });
  assert.equal(state.title, "盤點差異待入帳");
  assert.equal(state.variant, "is-alert");
  assert.match(state.copy, /有 2 項與帳面數量不同/);
  assert.match(state.copy, /才會寫入庫存異動/);
});

test("fully checked stocktake with no variance is ready but explicitly not posted", () => {
  const state = getState({ pendingCount: 3, verifiedCount: 3, varianceCount: 0 });
  assert.equal(state.title, "逐項核對完成，尚未入帳");
  assert.equal(state.variant, "is-success");
  assert.match(state.copy, /目前沒有數量差異/);
  assert.match(state.copy, /才會正式入帳/);
});

test("no selected location or no lines does not show a review hint", () => {
  assert.equal(getState({ locationSelected: false }), null);
  assert.equal(getState({ hasLines: false }), null);
});

test("fully applied stocktake uses the existing completion guide instead", () => {
  assert.equal(getState({ pendingCount: 0, verifiedCount: 0, varianceCount: 0, appliedCount: 3 }), null);
});
