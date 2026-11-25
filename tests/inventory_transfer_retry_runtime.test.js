import assert from "node:assert/strict";
import fs from "node:fs";
import vm from "node:vm";
import test from "node:test";

const html = fs.readFileSync("app/static/index.html", "utf8");
const helperNames = [
  "inventoryTransferPendingStorageKey",
  "readPendingInventoryTransfer",
  "savePendingInventoryTransfer",
  "clearPendingInventoryTransfer",
];

const helpers = helperNames.map((name) => {
  const escaped = name.replace(/[.*+?^\${}()|[\]\\]/g, "\\$&");
  const match = html.match(new RegExp("function " + escaped + "\\([\\s\\S]*?\\n\\}"));
  assert.ok(match, name + " must exist in the inventory page");
  return match[0];
}).join("\\n");

function createContext(initialValues = new Map()) {
  const values = new Map(initialValues);
  let nextKey = 0;
  const context = {
    localStorage: {
      getItem: (key) => values.get(key) ?? null,
      setItem: (key, value) => values.set(key, value),
      removeItem: (key) => values.delete(key),
    },
    crypto: {
      randomUUID: () => "00000000-0000-4000-8000-" + String(++nextKey).padStart(12, "0"),
    },
  };
  vm.createContext(context);
  vm.runInContext(helpers, context);
  return { context, values };
}

test("manual transfer retry key is scoped to company and site", () => {
  const { context } = createContext();
  assert.equal(
    context.inventoryTransferPendingStorageKey("company-1", "site-1"),
    "gold-erp:inventory-transfer:company-1:site-1",
  );
  assert.notEqual(
    context.inventoryTransferPendingStorageKey("company-1", "site-1"),
    context.inventoryTransferPendingStorageKey("company-1", "site-2"),
  );
});

test("exact retry reuses the original key and fingerprint", () => {
  const { context, values } = createContext();
  const payload = {
    site_id: "site-1",
    product_id: "product-1",
    from_location_id: "safe",
    to_location_id: "show",
    quantity: "2",
    note: "上架",
  };
  const first = context.savePendingInventoryTransfer("company-1", "site-1", payload);
  const replay = context.savePendingInventoryTransfer("company-1", "site-1", payload);
  assert.equal(first.key, replay.key);
  assert.equal(first.fingerprint, replay.fingerprint);
  assert.equal(values.size, 1);
});

test("changed content cannot replace an unresolved transfer", () => {
  const { context, values } = createContext();
  const original = {
    site_id: "site-1",
    product_id: "product-1",
    from_location_id: "safe",
    to_location_id: "show",
    quantity: "2",
    note: "上架",
  };
  const changed = { ...original, quantity: "3" };
  const first = context.savePendingInventoryTransfer("company-1", "site-1", original);
  assert.throws(
    () => context.savePendingInventoryTransfer("company-1", "site-1", changed),
    /不可修改內容另送/,
  );
  const saved = context.readPendingInventoryTransfer("company-1", "site-1");
  assert.equal(saved.key, first.key);
  assert.equal(saved.fingerprint, first.fingerprint);
  assert.equal(values.size, 1);
});

test("clearing a confirmed transfer removes only that site pending request", () => {
  const { context, values } = createContext();
  const payload = { site_id: "site-1", product_id: "product-1", quantity: "1" };
  context.savePendingInventoryTransfer("company-1", "site-1", payload);
  context.savePendingInventoryTransfer("company-1", "site-2", { ...payload, site_id: "site-2" });
  context.clearPendingInventoryTransfer("company-1", "site-1");
  assert.equal(context.readPendingInventoryTransfer("company-1", "site-1"), null);
  assert.ok(context.readPendingInventoryTransfer("company-1", "site-2"));
  assert.equal(values.size, 1);
});

test("malformed pending data is not silently discarded", () => {
  const key = "gold-erp:inventory-transfer:company-1:site-1";
  const { context } = createContext(new Map([[key, "{not valid json"]]));
  const pending = context.readPendingInventoryTransfer("company-1", "site-1");
  assert.deepEqual(JSON.parse(JSON.stringify(pending)), { invalid: true });
});
