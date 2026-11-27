import assert from "node:assert/strict";
import fs from "node:fs";
import test from "node:test";
import vm from "node:vm";

const html = fs.readFileSync("app/static/index.html", "utf8");
const startMarker = "function cashDrawerOperatorStorageKey(company,site){";
const endMarker = "function cashDrawerPendingStorageKey(company,site){";
const start = html.indexOf(startMarker);
const end = html.indexOf(endMarker, start);
assert.notEqual(start, -1, "Cash drawer operator memory helpers must exist");
assert.notEqual(end, -1, "Cash drawer operator helpers must end before pending movement storage");
const source = html.slice(start, end);

class MemoryStorage {
  constructor(seed = {}) {
    this.values = new Map(Object.entries(seed));
  }
  getItem(key) {
    return this.values.has(key) ? this.values.get(key) : null;
  }
  setItem(key, value) {
    this.values.set(key, String(value));
  }
  removeItem(key) {
    this.values.delete(key);
  }
}

function setup(storage = new MemoryStorage()) {
  const actor = { value: "" };
  const context = {
    localStorage: storage,
    companyId: "company-1",
    selectedSiteId: "site-1",
    $: (id) => id === "drawerActor" ? actor : null,
  };
  vm.createContext(context);
  vm.runInContext(source, context);
  return { context, actor, storage };
}

test("cash drawer operator memory is isolated by company and site", () => {
  const { context } = setup();
  const firstKey = context.cashDrawerOperatorStorageKey("company-1", "site-1");
  assert.equal(firstKey, "gold-erp-cash-drawer-operator:company-1:site-1");
  assert.notEqual(firstKey, context.cashDrawerOperatorStorageKey("company-1", "site-2"));
  assert.notEqual(firstKey, context.cashDrawerOperatorStorageKey("company-2", "site-1"));
});

test("only a non-empty successful operator name is saved and restored", () => {
  const { context } = setup();
  assert.equal(context.saveCashDrawerOperator("company-1", "site-1", "  王小明  "), true);
  assert.equal(context.readCashDrawerOperator("company-1", "site-1"), "王小明");
  assert.equal(context.readCashDrawerOperator("company-1", "site-2"), "");
  assert.equal(context.saveCashDrawerOperator("company-1", "site-1", "   "), false);
  assert.equal(context.saveCashDrawerOperator("", "site-1", "王小明"), false);
  assert.equal(context.saveCashDrawerOperator("company-1", "", "王小明"), false);
});

test("operator restore does not overwrite a name already being edited unless forced", () => {
  const { context, actor } = setup();
  context.saveCashDrawerOperator("company-1", "site-1", "王小明");
  actor.value = "林小姐";
  context.restoreCashDrawerOperator();
  assert.equal(actor.value, "林小姐");
  context.restoreCashDrawerOperator(true);
  assert.equal(actor.value, "王小明");
});

test("switching sites restores that site's operator and clears the previous site's value when none exists", () => {
  const { context, actor } = setup();
  context.saveCashDrawerOperator("company-1", "site-1", "王小明");
  context.saveCashDrawerOperator("company-1", "site-2", "林小姐");

  context.selectedSiteId = "site-2";
  context.restoreCashDrawerOperator(true);
  assert.equal(actor.value, "林小姐");

  context.selectedSiteId = "site-3";
  context.restoreCashDrawerOperator(true);
  assert.equal(actor.value, "");
});

test("operator memory safely degrades when browser storage is unavailable", () => {
  const brokenStorage = {
    getItem() { throw new Error("storage blocked"); },
    setItem() { throw new Error("storage blocked"); },
  };
  const { context, actor } = setup(brokenStorage);
  assert.equal(context.readCashDrawerOperator("company-1", "site-1"), "");
  assert.equal(context.saveCashDrawerOperator("company-1", "site-1", "王小明"), false);
  actor.value = "";
  assert.doesNotThrow(() => context.restoreCashDrawerOperator(true));
  assert.equal(actor.value, "");
});

test("successful cash drawer entries retain only the operator and return focus to amount", () => {
  const submitStart = html.indexOf('$("cashDrawerForm").addEventListener("submit"');
  const submitEnd = html.indexOf('$("refreshCashDrawer").addEventListener', submitStart);
  assert.notEqual(submitStart, -1);
  assert.notEqual(submitEnd, -1);
  const handler = html.slice(submitStart, submitEnd);
  const apiCall = handler.indexOf('await api("/companies/"+companyId+"/sites/"+selectedSiteId+"/cash-drawer-movements"');
  const save = handler.indexOf("saveCashDrawerOperator(companyId,selectedSiteId,payload.created_by_name)");
  const reset = handler.indexOf('$("cashDrawerForm").reset()');
  const restore = handler.indexOf("restoreCashDrawerOperator(true)");
  const focus = handler.indexOf('nextDrawerAmount.focus({preventScroll:true})');
  assert.ok(apiCall >= 0 && save > apiCall, "operator must be remembered only after the API confirms success");
  assert.ok(reset > save && restore > reset && focus > restore, "reset must be followed by operator restore and amount focus");
  assert.match(handler, /clearPendingCashDrawerMovement\(companyId,selectedSiteId\)/);
  assert.match(handler, /saveCashDrawerOperator\(companyId,selectedSiteId,payload\.created_by_name\)/);
});
