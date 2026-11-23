import assert from "node:assert/strict";
import fs from "node:fs";
import test from "node:test";
import vm from "node:vm";

const html = fs.readFileSync("app/static/index.html", "utf8");
const startMarker = "function pendingExpenseStorageKey(company,site){";
const endMarker = "\nasync function loadExpenses(){";
const start = html.indexOf(startMarker);
const end = html.indexOf(endMarker, start);
assert.notEqual(start, -1, "Operating expense retry helpers must exist");
assert.notEqual(end, -1, "Operating expense helper block must end before list loader");
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
  const messages = [];
  const context = {
    localStorage: storage,
    companyId: "company-1",
    selectedSiteId: "site-1",
    $: () => ({ classList: { toggle() {} }, value: "" }),
    message: (...args) => messages.push(args),
  };
  vm.createContext(context);
  vm.runInContext(source, context);
  return { context, storage, messages };
}

test("expense create retry payload survives reload and rejects edited content", () => {
  const storage = new MemoryStorage();
  const firstPage = setup(storage);
  const payload = {
    site_id: "site-1",
    expense_no: "EXP-001",
    expense_date: "2026-11-23",
    category_code: "UTILITIES",
    description: "店面水電費",
    amount: "1200.00",
    payee: "台電",
    payment_method: null,
    receipt_no: "INV-001",
    note: "11 月電費",
  };
  const saved = firstPage.context.savePendingExpense("company-1", "site-1", payload);
  assert.equal(saved.payload.expense_no, "EXP-001");

  const reloaded = setup(storage);
  const restored = reloaded.context.readPendingExpense("company-1", "site-1");
  assert.deepEqual(JSON.parse(JSON.stringify(restored.payload)), payload);
  assert.equal(restored.fingerprint, JSON.stringify(payload));
  assert.equal(
    reloaded.context.savePendingExpense("company-1", "site-1", payload).fingerprint,
    restored.fingerprint,
  );
  assert.throws(
    () => reloaded.context.savePendingExpense(
      "company-1", "site-1", { ...payload, amount: "1300.00" },
    ),
    /上一筆營業費用尚未確認結果/,
  );
});

test("expense create pending record is removed only after explicit success clear", () => {
  const { context, storage } = setup();
  const payload = { expense_no: "EXP-002", amount: "88.00" };
  const key = context.pendingExpenseStorageKey("company-1", "site-1");
  context.savePendingExpense("company-1", "site-1", payload);
  assert.notEqual(storage.getItem(key), null);
  context.clearPendingExpense("company-1", "site-1");
  assert.equal(storage.getItem(key), null);
  assert.equal(context.readPendingExpense("company-1", "site-1"), null);
});

test("expense payment retry retains the original method after reload", () => {
  const storage = new MemoryStorage();
  const firstPage = setup(storage);
  firstPage.context.savePendingExpensePayment(
    "company-1", "site-1", "expense-1", "TRANSFER",
  );
  const reloaded = setup(storage);
  const restored = reloaded.context.readPendingExpensePayment(
    "company-1", "site-1", "expense-1",
  );
  assert.equal(restored.payment_method, "TRANSFER");
  assert.equal(
    reloaded.context.savePendingExpensePayment(
      "company-1", "site-1", "expense-1", "TRANSFER",
    ).payment_method,
    "TRANSFER",
  );
  assert.throws(
    () => reloaded.context.savePendingExpensePayment(
      "company-1", "site-1", "expense-1", "CASH",
    ),
    /上一筆費用付款尚未確認結果/,
  );
});

test("expense payment pending record clears only after confirmed completion", () => {
  const { context, storage } = setup();
  const key = context.expensePaymentPendingStorageKey(
    "company-1", "site-1", "expense-2",
  );
  context.savePendingExpensePayment(
    "company-1", "site-1", "expense-2", "CASH",
  );
  assert.notEqual(storage.getItem(key), null);
  context.clearPendingExpensePayment("company-1", "site-1", "expense-2");
  assert.equal(storage.getItem(key), null);
  assert.equal(
    context.readPendingExpensePayment("company-1", "site-1", "expense-2"),
    null,
  );
});

test("corrupted expense drafts are safely discarded", () => {
  const key = "gold-erp-expense-create:company-1:site-1";
  const storage = new MemoryStorage({ [key]: "{invalid-json" });
  const { context } = setup(storage);
  assert.doesNotThrow(
    () => context.readPendingExpense("company-1", "site-1"),
  );
  assert.equal(context.readPendingExpense("company-1", "site-1"), null);
  assert.equal(storage.getItem(key), null);
});
