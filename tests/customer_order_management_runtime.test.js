import assert from "node:assert/strict";
import fs from "node:fs";
import test from "node:test";

const html = fs.readFileSync("app/static/index.html", "utf8");
const router = fs.readFileSync("app/routers/customer_orders.py", "utf8");
const schema = fs.readFileSync("app/routers/schemas/customer_orders.py", "utf8");

test("customer order list supports editing basic data and fulfillment status transitions", () => {
  assert.match(html, /customerOrderList/);
  assert.match(html, /data-edit-customer-order=/);
  assert.match(html, /data-next-customer-order-status=/);
  assert.match(html, /customerOrderEditForm/);
  assert.match(html, /customer-orders\/\+editingCustomerOrderId/);
});

test("customer order edit keeps paid amounts and item snapshots immutable", () => {
  assert.match(router, /order\.status != "IN_PROGRESS"/);
  assert.match(schema, /class CustomerOrderUpdate/);
  assert.match(schema, /extra="forbid"/);
  assert.match(html, /已收訂金、商品明細及金額快照不在此處改寫/);
  assert.match(html, /取消訂單需先完成退款流程/);
});
