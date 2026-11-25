import assert from "node:assert/strict";
import fs from "node:fs";
import vm from "node:vm";
import test from "node:test";

const html = fs.readFileSync("app/static/index.html", "utf8");
const helperNames = [
  "inventoryAdjustmentPendingStorageKey",
  "readPendingInventoryAdjustment",
  "savePendingInventoryAdjustment",
  "clearPendingInventoryAdjustment",
];

const helpers = helperNames.map((name) => {
  const match = html.match(new RegExp("function " + name + "\\([\\s\\S]*?\\n\\}"));
  assert.ok(match, name + " must exist in the inventory page");
  return match[0];
}).join("\n");

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
      randomUUID: () => "10000000-0000-4000-8000-" + String(++nextKey).padStart(12, "0"),
    },
  };
  vm.createContext(context);
  vm.runInContext(helpers, context);
  return { context, values };
}

test("manual adjustment pending key is scoped to company and site", () => {
  const { context } = createContext();
  assert.equal(
    context.inventoryAdjustmentPendingStorageKey("company-1", "site-1"),
    "gold-erp:inventory-adjustment:company-1:site-1",
  );
  assert.notEqual(
    context.inventoryAdjustmentPendingStorageKey("company-1", "site-1"),
    context.inventoryAdjustmentPendingStorageKey("company-1", "site-2"),
  );
});

test("exact manual adjustment retry reuses the original UUID and payload fingerprint", () => {
  const { context, values } = createContext();
  const payload = {
    site_id: "site-1",
    product_id: "product-1",
    location_id: "safe",
    direction: "OUT",
    quantity: "2",
    weight: "1.0000",
    weight_unit_code: "QIAN",
    note: "盤點差異",
  };
  const first = context.savePendingInventoryAdjustment("company-1", "site-1", payload);
  const replay = context.savePendingInventoryAdjustment("company-1", "site-1", payload);
  assert.equal(first.key, replay.key);
  assert.equal(first.fingerprint, replay.fingerprint);
  assert.deepEqual(JSON.parse(JSON.stringify(replay.payload)), payload);
  assert.equal(values.size, 1);
});

test("changed manual adjustment content cannot replace an unresolved request", () => {
  const { context, values } = createContext();
  const original = {
    site_id: "site-1",
    product_id: "product-1",
    location_id: "safe",
    direction: "OUT",
    quantity: "2",
    weight: "1.0000",
    weight_unit_code: "QIAN",
    note: "盤點差異",
  };
  const changed = { ...original, quantity: "3" };
  const first = context.savePendingInventoryAdjustment("company-1", "site-1", original);
  assert.throws(
    () => context.savePendingInventoryAdjustment("company-1", "site-1", changed),
    /不可修改內容另送/,
  );
  const saved = context.readPendingInventoryAdjustment("company-1", "site-1");
  assert.equal(saved.key, first.key);
  assert.equal(saved.fingerprint, first.fingerprint);
  assert.equal(values.size, 1);
});

test("clearing a confirmed adjustment removes only its site pending request", () => {
  const { context, values } = createContext();
  const payload = {
    site_id: "site-1",
    product_id: "product-1",
    location_id: "safe",
    direction: "IN",
    quantity: "1",
    note: null,
  };
  context.savePendingInventoryAdjustment("company-1", "site-1", payload);
  context.savePendingInventoryAdjustment("company-1", "site-2", { ...payload, site_id: "site-2" });
  context.clearPendingInventoryAdjustment("company-1", "site-1");
  assert.equal(context.readPendingInventoryAdjustment("company-1", "site-1"), null);
  assert.ok(context.readPendingInventoryAdjustment("company-1", "site-2"));
  assert.equal(values.size, 1);
});

test("malformed pending manual adjustment data is retained for reconciliation", () => {
  const key = "gold-erp:inventory-adjustment:company-1:site-1";
  const { context, values } = createContext(new Map([[key, "{not valid json"]]));
  const pending = context.readPendingInventoryAdjustment("company-1", "site-1");
  assert.deepEqual(JSON.parse(JSON.stringify(pending)), { invalid: true });
  assert.equal(values.get(key), "{not valid json");
});
