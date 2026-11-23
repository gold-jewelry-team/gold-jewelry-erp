import assert from "node:assert/strict";
import fs from "node:fs";
import test from "node:test";
import vm from "node:vm";

const html = fs.readFileSync("app/static/index.html", "utf8");
const startMarker = "function supplierPaymentPendingStorageKey(company,site,bill){";
const endMarker = '\n$("supplierPaymentForm").addEventListener';
const start = html.indexOf(startMarker);
const end = html.indexOf(endMarker, start);
assert.notEqual(start, -1, "Supplier payment pending storage helpers must exist");
assert.notEqual(end, -1, "Supplier payment storage helpers must end before form submit handler");
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
  const context = { localStorage: storage };
  vm.createContext(context);
  vm.runInContext(source, context);
  return { context, storage };
}

test("supplier payment retry storage is scoped by company, site and bill", () => {
  const { context } = setup();
  assert.equal(
    context.supplierPaymentPendingStorageKey("company-1", "site-1", "bill-1"),
    "gold-erp-supplier-payment:company-1:site-1:bill-1",
  );
  assert.notEqual(
    context.supplierPaymentPendingStorageKey("company-1", "site-1", "bill-1"),
    context.supplierPaymentPendingStorageKey("company-1", "site-2", "bill-1"),
  );
});

test("supplier payment pending payload survives page reload and exact retry", () => {
  const storage = new MemoryStorage();
  const firstPage = setup(storage);
  const payload = {
    site_id: "site-1",
    supplier_id: "supplier-1",
    payment_no: "SP-001",
    payment_method: "TRANSFER",
    allocations: [{ bill_id: "bill-1", amount: "350.00" }],
    reference_no: "BANK-001",
    note: "進貨貨款",
  };

  const saved = firstPage.context.savePendingSupplierPayment(
    "company-1", "site-1", "bill-1", payload,
  );
  assert.equal(saved.payload.payment_no, "SP-001");

  // A new VM represents a refreshed/reopened browser page using the same storage.
  const reloadedPage = setup(storage);
  const restored = reloadedPage.context.readPendingSupplierPayment(
    "company-1", "site-1", "bill-1",
  );
  assert.deepEqual(JSON.parse(JSON.stringify(restored.payload)), payload);
  assert.equal(restored.fingerprint, JSON.stringify(payload));

  const sameRequest = reloadedPage.context.savePendingSupplierPayment(
    "company-1", "site-1", "bill-1", payload,
  );
  assert.equal(sameRequest.fingerprint, restored.fingerprint);
});

test("supplier payment pending payload blocks edits until original request is resolved", () => {
  const { context } = setup();
  const original = {
    payment_no: "SP-002",
    allocations: [{ bill_id: "bill-2", amount: "200.00" }],
  };
  const changed = {
    payment_no: "SP-002-NEW",
    allocations: [{ bill_id: "bill-2", amount: "250.00" }],
  };

  context.savePendingSupplierPayment("company-1", "site-1", "bill-2", original);
  assert.throws(
    () => context.savePendingSupplierPayment("company-1", "site-1", "bill-2", changed),
    /上一筆供應商付款尚未確認結果/,
  );
  assert.deepEqual(
    JSON.parse(JSON.stringify(
      context.readPendingSupplierPayment("company-1", "site-1", "bill-2").payload
    )),
    original,
  );
});

test("supplier payment pending record is removed only when explicitly cleared", () => {
  const { context, storage } = setup();
  const payload = {
    payment_no: "SP-003",
    allocations: [{ bill_id: "bill-3", amount: "50.00" }],
  };
  const key = context.supplierPaymentPendingStorageKey("company-1", "site-1", "bill-3");
  context.savePendingSupplierPayment("company-1", "site-1", "bill-3", payload);
  assert.notEqual(storage.getItem(key), null);

  context.clearPendingSupplierPayment("company-1", "site-1", "bill-3");
  assert.equal(storage.getItem(key), null);
  assert.equal(context.readPendingSupplierPayment("company-1", "site-1", "bill-3"), null);
});

test("corrupted supplier payment local draft is safely discarded", () => {
  const key = "gold-erp-supplier-payment:company-1:site-1:bill-4";
  const storage = new MemoryStorage({ [key]: "{invalid-json" });
  const { context } = setup(storage);

  assert.doesNotThrow(
    () => context.readPendingSupplierPayment("company-1", "site-1", "bill-4"),
  );
  assert.equal(context.readPendingSupplierPayment("company-1", "site-1", "bill-4"), null);
  assert.equal(storage.getItem(key), null);
});
