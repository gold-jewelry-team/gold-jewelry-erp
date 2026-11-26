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
  assert.match(html, /data-create-customer-order-sale=/);
  assert.match(html, /data-open-customer-order-sale=/);
  assert.match(html, /function startCustomerOrderSale/);
  assert.match(html, /完成銷售後才會扣庫存/);
  assert.ok(html.includes('"/customer-orders/"+editingCustomerOrderId'));
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
  assert.match(router, /客訂完成交貨必須透過正式銷售單完成/);
  assert.match(paymentService, /direction="OUT"/);
  assert.match(paymentService, /CO-REFUND:/);
  assert.match(paymentService, /order\.deposit_amount -= amount/);
  assert.match(schema, /if self\.status == "CANCELLED"/);
});


test("customer order owner screen supports extra collections and final balance payments", () => {
  assert.match(html, /data-add-customer-order-payment=/);
  assert.match(html, /登錄追加收款／尾款/);
  assert.match(html, /balance_amount/);
  assert.ok(html.includes('"/customer-orders/"+row.id+"/payments"'));
  assert.match(schema, /class CustomerOrderPaymentCreate/);
});

test("customer order collections and refunds preserve the same idempotency request after reload", () => {
  assert.match(html, /customerOrderOperationStorageKey/);
  assert.match(html, /readPendingCustomerOrderOperation/);
  assert.match(html, /savePendingCustomerOrderOperation/);
  assert.match(html, /clearPendingCustomerOrderOperation/);
  assert.match(html, /idempotency_key:newCustomerOrderIdempotencyKey\(\)/);
  assert.match(html, /恢復待確認收款/);
  assert.match(html, /恢復待確認退款/);
  assert.ok(html.includes('"/customer-orders/"+row.id+"/refunds"'));
});

test("customer order status transitions lock the order row before changing fulfillment state", () => {
  const statusHandler = router.slice(router.indexOf('def update_customer_order_status'));
  assert.match(statusHandler, /with_for_update\(\)/);
});
