import assert from "node:assert/strict";
import fs from "node:fs";
import test from "node:test";
import vm from "node:vm";

const html = fs.readFileSync("app/static/index.html", "utf8");
const startMarker = "const paymentIdempotencyMemory=new Map();";
const endMarker = "\\nconst statusMessageTimers=new Map();";
const start = html.indexOf(startMarker);
const end = html.indexOf(endMarker, start);
assert.notEqual(start, -1, "Payment idempotency helpers must exist");
assert.notEqual(end, -1, "Payment retry helpers must end before status message helpers");
const source = html.slice(start, end);

const saleHandlerStart = html.indexOf('$("salePaymentForm").addEventListener("submit"');
const saleHandlerEnd = html.indexOf("\\n});", saleHandlerStart) + 4;
const returnHandlerStart = html.indexOf('$("returnPaymentForm").addEventListener("submit"');
const returnHandlerEnd = html.indexOf("\\n});", returnHandlerStart) + 4;
assert.notEqual(saleHandlerStart, -1, "Sale payment form handler must exist");
assert.notEqual(returnHandlerStart, -1, "Return payment form handler must exist");
const saleHandler = html.slice(saleHandlerStart, saleHandlerEnd);
const returnHandler = html.slice(returnHandlerStart, returnHandlerEnd);

class MemoryStorage {
  constructor(seed = {}, { failReads = false, failWrites = false } = {}) {
    this.values = new Map(Object.entries(seed));
    this.failReads = failReads;
    this.failWrites = failWrites;
  }

  getItem(key) {
    if (this.failReads) throw new Error("storage read blocked");
    return this.values.has(key) ? this.values.get(key) : null;
  }

  setItem(key, value) {
    if (this.failWrites) throw new Error("storage write blocked");
    this.values.set(key, String(value));
  }

  removeItem(key) {
    if (this.failWrites) throw new Error("storage write blocked");
    this.values.delete(key);
  }
}

function setup(storage = new MemoryStorage()) {
  const context = {
    localStorage: storage,
    window: { crypto: { randomUUID: () => "11111111-2222-4333-8444-555555555555" } },
    companyId: "company-1",
  };
  vm.createContext(context);
  vm.runInContext(source, context);
  return { context, storage };
}

test("payment retry key is scoped by company, payment type and source", () => {
  const { context } = setup();
  const sale = context.paymentIdempotencyStorageKey("sale", "sale-1");
  const returned = context.paymentIdempotencyStorageKey("return", "return-1");
  assert.equal(sale, "gold-erp-payment:sale:company-1:sale-1");
  assert.equal(returned, "gold-erp-payment:return:company-1:return-1");
  assert.notEqual(sale, returned);
});

test("exact sale or return payment retry reuses the original key after reload", () => {
  const storage = new MemoryStorage();
  const payload = {
    payment_method: "TRANSFER",
    amount: "120.00",
    reference_no: "BANK-REFUND-001",
    note: "退貨轉帳退款",
  };

  const firstPage = setup(storage);
  const firstKey = firstPage.context.getPaymentIdempotencyKey("return", "return-1", payload);
  assert.ok(firstKey);

  const reloadedPage = setup(storage);
  const retryKey = reloadedPage.context.getPaymentIdempotencyKey("return", "return-1", payload);
  assert.equal(retryKey, firstKey);
});

test("pending payment blocks changed amount, method, reference or note", () => {
  const { context, storage } = setup();
  const original = {
    payment_method: "TRANSFER",
    amount: "120.00",
    reference_no: "BANK-REFUND-001",
    note: "退貨轉帳退款",
  };
  const key = context.getPaymentIdempotencyKey("return", "return-2", original);

  const edits = [
    { ...original, amount: "100.00" },
    { ...original, payment_method: "CASH" },
    { ...original, reference_no: "BANK-REFUND-002" },
    { ...original, note: "改過的退款備註" },
  ];
  for (const edited of edits) {
    assert.throws(
      () => context.getPaymentIdempotencyKey("return", "return-2", edited),
      /上一筆收付款尚未確認結果/,
    );
  }

  const restoredKey = context.getPaymentIdempotencyKey("return", "return-2", original);
  assert.equal(restoredKey, key);
  const saved = JSON.parse(storage.getItem(
    context.paymentIdempotencyStorageKey("return", "return-2"),
  ));
  assert.equal(saved.key, key);
  assert.equal(saved.fingerprint, JSON.stringify(original));
});

test("sale payment edit is blocked until the pending request is resolved", () => {
  const { context } = setup();
  const original = {
    payment_method: "CASH",
    amount: "500.00",
    reference_no: null,
    note: null,
  };
  const key = context.getPaymentIdempotencyKey("sale", "sale-1", original);
  assert.throws(
    () => context.getPaymentIdempotencyKey(
      "sale", "sale-1", { ...original, amount: "300.00" },
    ),
    /上一筆收付款尚未確認結果/,
  );
  assert.equal(context.getPaymentIdempotencyKey("sale", "sale-1", original), key);
});

test("payment retry remains protected during the session when browser storage is unavailable", () => {
  const storage = new MemoryStorage({}, { failReads: true, failWrites: true });
  const { context } = setup(storage);
  const original = {
    payment_method: "CARD",
    amount: "80.00",
    reference_no: null,
    note: null,
  };
  const key = context.getPaymentIdempotencyKey("sale", "sale-2", original);
  assert.ok(key);
  assert.throws(
    () => context.getPaymentIdempotencyKey(
      "sale", "sale-2", { ...original, amount: "70.00" },
    ),
    /上一筆收付款尚未確認結果/,
  );
});

test("confirmed success or explicit 4xx rejection can clear the pending payment key", () => {
  const { context, storage } = setup();
  const payload = {
    payment_method: "CASH",
    amount: "50.00",
    reference_no: null,
    note: null,
  };
  const key = context.getPaymentIdempotencyKey("sale", "sale-3", payload);
  const storageKey = context.paymentIdempotencyStorageKey("sale", "sale-3");
  assert.notEqual(storage.getItem(storageKey), null);

  context.clearPaymentIdempotencyKey("sale", "sale-3", key);
  assert.equal(storage.getItem(storageKey), null);
  assert.notEqual(
    context.getPaymentIdempotencyKey("sale", "sale-3", payload),
    key,
  );
});

test("sale and return form handlers catch pending-payload mismatch and always re-enable submit", () => {
  assert.match(
    saleHandler,
    /let idempotencyKey=null;\\s*try\\s*\\{\\s*idempotencyKey=getPaymentIdempotencyKey\\("sale"/,
  );
  assert.match(
    returnHandler,
    /let idempotencyKey=null;\\s*try\\s*\\{\\s*idempotencyKey=getPaymentIdempotencyKey\\("return"/,
  );
  assert.match(saleHandler, /finally\\s*\\{button.disabled=false;\\}/);
  assert.match(returnHandler, /finally\\s*\\{button.disabled=false;\\}/);
});
