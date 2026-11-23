import assert from "node:assert/strict";
import fs from "node:fs";
import test from "node:test";
import vm from "node:vm";

const html = fs.readFileSync("app/static/index.html", "utf8");
const startMarker = "function cashDrawerPendingStorageKey(company,site){";
const endMarker = "\nasync function loadCashDrawerMovements(){";
const start = html.indexOf(startMarker);
const end = html.indexOf(endMarker, start);
assert.notEqual(start, -1, "Cash drawer retry helpers must exist");
assert.notEqual(end, -1, "Cash drawer helpers must end before the list loader");
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
  const context = {
    localStorage: storage,
    window: { crypto: { randomUUID: () => "11111111-2222-4333-8444-555555555555" } },
    companyId: "company-1",
    selectedSiteId: "site-1",
    $: () => ({ classList: { toggle() {} }, value: "" }),
    message() {},
  };
  vm.createContext(context);
  vm.runInContext(source, context);
  return { context, storage };
}

test("cash drawer retry draft is scoped by company and site", () => {
  const { context } = setup();
  assert.equal(
    context.cashDrawerPendingStorageKey("company-1", "site-1"),
    "gold-erp-cash-drawer:company-1:site-1",
  );
  assert.notEqual(
    context.cashDrawerPendingStorageKey("company-1", "site-1"),
    context.cashDrawerPendingStorageKey("company-1", "site-2"),
  );
});

test("cash drawer movement retry survives reload and retains the original key", () => {
  const storage = new MemoryStorage();
  const firstPage = setup(storage);
  const payload = {
    movement_type: "BANK_DEPOSIT",
    amount: "400.00",
    description: "存入銀行",
    created_by_name: "店員甲",
    reference_no: "BANK-001",
    note: "當日存款",
  };
  const first = firstPage.context.savePendingCashDrawerMovement(
    "company-1", "site-1", payload,
  );
  assert.equal(first.payload.movement_type, "BANK_DEPOSIT");
  assert.ok(first.idempotency_key);

  const reloaded = setup(storage);
  const restored = reloaded.context.readPendingCashDrawerMovement(
    "company-1", "site-1",
  );
  assert.deepEqual(JSON.parse(JSON.stringify(restored.payload)), payload);
  assert.equal(restored.idempotency_key, first.idempotency_key);
  assert.equal(
    reloaded.context.savePendingCashDrawerMovement(
      "company-1", "site-1", payload,
    ).idempotency_key,
    first.idempotency_key,
  );
});

test("cash drawer retry blocks edited amount or movement type until resolved", () => {
  const { context } = setup();
  const original = {
    movement_type: "BANK_WITHDRAWAL",
    amount: "100.00",
    description: "銀行提款",
    created_by_name: "店員甲",
    reference_no: null,
    note: null,
  };
  context.savePendingCashDrawerMovement("company-1", "site-1", original);
  assert.throws(
    () => context.savePendingCashDrawerMovement(
      "company-1", "site-1", { ...original, amount: "150.00" },
    ),
    /上一筆現金櫃異動尚未確認結果/,
  );
});

test("cash drawer pending record clears only after confirmed success", () => {
  const { context, storage } = setup();
  const key = context.cashDrawerPendingStorageKey("company-1", "site-1");
  context.savePendingCashDrawerMovement("company-1", "site-1", {
    movement_type: "OTHER_IN",
    amount: "20.00",
    description: "零錢補入",
    created_by_name: "店員甲",
    reference_no: null,
    note: null,
  });
  assert.notEqual(storage.getItem(key), null);
  context.clearPendingCashDrawerMovement("company-1", "site-1");
  assert.equal(storage.getItem(key), null);
  assert.equal(context.readPendingCashDrawerMovement("company-1", "site-1"), null);
});

test("corrupted cash drawer retry draft is safely discarded", () => {
  const key = "gold-erp-cash-drawer:company-1:site-1";
  const storage = new MemoryStorage({ [key]: "{invalid-json" });
  const { context } = setup(storage);
  assert.doesNotThrow(
    () => context.readPendingCashDrawerMovement("company-1", "site-1"),
  );
  assert.equal(context.readPendingCashDrawerMovement("company-1", "site-1"), null);
  assert.equal(storage.getItem(key), null);
});
