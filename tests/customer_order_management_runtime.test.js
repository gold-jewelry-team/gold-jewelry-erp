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
  assert.ok(html.includes('"/customer-orders/"+editingCustomerOrderId'));
  assert.match(html, /customer-orders\/\+editingCustomerOrderId/);
});

test("customer order edit keeps paid amounts and item snapshots immutable", () => {
  assert.match(router, /order\.status != "IN_PROGRESS"/);
  assert.match(schema, /class CustomerOrderUpdate/);
  assert.match(schema, /extra="forbid"/);
  assert.match(html, /已收訂金、商品明細及金額快照不在此處改寫/);
  assert.match(html, /取消訂單需先完成退款流程/);
});


test("customer order refunds are append-only and cancellation requires full refund", () => {
  const paymentService = fs.readFileSync("app/services/payments.py", "utf8");
  assert.match(html, /data-refund-customer-order=/);
  assert.match(html, /data-cancel-customer-order=/);
  assert.ok(html.includes('"/customer-orders/"+row.id+"/refunds"'));
  assert.ok(html.includes('"/customer-orders/"+row.id+"/cancel"'));
  assert.match(router, /@router\.post\("\/\{order_id\}\/refunds"/);
  assert.match(router, /@router\.post\("\/\{order_id\}\/cancel"/);
  assert.match(paymentService, /direction="OUT"/);
  assert.match(paymentService, /CO-REFUND:/);
  assert.match(paymentService, /order\.deposit_amount -= amount/);
  assert.match(schema, /if self\.status == "CANCELLED"/);
});
