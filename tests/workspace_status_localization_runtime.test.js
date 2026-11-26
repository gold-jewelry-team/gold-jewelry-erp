import assert from "node:assert/strict";
import fs from "node:fs";
import test from "node:test";

const read = (path) => fs.readFileSync(path, "utf8");
const sales = read("app/static/employee_sales.html");
const purchases = read("app/static/employee_purchases.html");
const payables = read("app/static/employee_payables.html");
const orders = read("app/static/employee_customer_orders.html");
const catalog = read("app/static/employee_catalog.html");
const goldMaterial = read("app/static/gold_material.html");
const mainWorkspace = read("app/static/index.html");

const localizedUnknownStatus = /label:(?:status|bill\.status|order\.status)\?"其他狀態":"狀態未設定"/;

test("employee sales and purchase histories never expose unknown status codes", () => {
  assert.match(sales, /return map\[status\]\|\|\{label:status\?"其他狀態":"狀態未設定",cls:"badge"\}/);
  assert.match(purchases, /return map\[status\]\|\|\{label:status\?"其他狀態":"狀態未設定",cls:"badge"\}/);
  assert.doesNotMatch(sales, /label:status\|\|"未知"/);
  assert.doesNotMatch(purchases, /label:status\|\|"未知"/);
});

test("supplier payable history uses localized fallbacks for bill status and payment method", () => {
  assert.match(payables, /billStatusMap\[bill\.status\]\|\|\{label:bill\.status\?"其他狀態":"狀態未設定",cls:"badge"\}/);
  assert.match(payables, /function paymentMethodLabel\(value\)\{return paymentLabels\[value\]\|\|\(value\?"其他付款方式":"付款方式未設定"\);\}/);
  assert.match(payables, /paymentMethodLabel\(payment\.payment_method\)/);
  assert.doesNotMatch(payables, /paymentLabels\[payment\.payment_method\]\|\|payment\.payment_method/);
});

test("customer order history localizes status, payment method, and payment direction fallbacks", () => {
  assert.match(orders, /statusMap\[order\.status\]\|\|\{label:order\.status\?"其他狀態":"狀態未設定",cls:"badge"\}/);
  assert.match(orders, /function paymentMethodLabel\(value\)\{return paymentMethodLabels\[value\]\|\|\(value\?"其他付款方式":"付款方式未設定"\);\}/);
  assert.match(orders, /收付方向未設定/);
  assert.doesNotMatch(orders, /paymentMethodLabels\[payment\.payment_method\]\|\|payment\.payment_method/);
});

test("employee workspaces display weight units in Traditional Chinese", () => {
  for (const [name, html] of [
    ["sales", sales],
    ["purchases", purchases],
    ["orders", orders],
    ["catalog", catalog],
    ["gold material", goldMaterial],
  ]) {
    assert.match(html, /weightUnitLabels=\{G:"公克",QIAN:"錢",LIANG:"兩"\}/, name);
    assert.match(html, /function weightUnitLabel\(unit\)/, name);
  }
  assert.doesNotMatch(sales, /\+formatWeight\([^)]*\)\s*\+\s*\(unit\|\|""\)/);
  assert.doesNotMatch(purchases, /line\.weight_unit_code\|\|""/);
  assert.doesNotMatch(orders, /item\.weight_unit_code\|\|""/);
  assert.doesNotMatch(catalog, /product\.weight_unit_code\|\|""/);
  assert.doesNotMatch(goldMaterial, /esc\(x\.weight_unit_code\)/);
});

test("gold material movement history never exposes unknown movement type codes", () => {
  assert.match(goldMaterial, /typeLabels\[x\.movement_type\]\|\|"其他金料異動"/);
  assert.doesNotMatch(goldMaterial, /typeLabels\[x\.movement_type\]\|\|x\.movement_type/);
});


test("main business workspace uses Traditional Chinese fallbacks for statuses, payments, directions, and operation types", () => {
  assert.match(mainWorkspace, /function statusDisplayLabel\(value,labels\)/);
  assert.match(mainWorkspace, /function paymentMethodDisplayLabel\(value,labels=paymentMethodLabels\)/);
  assert.match(mainWorkspace, /function directionDisplayLabel\(value,labels\)/);
  assert.match(mainWorkspace, /其他區域類型/);
  assert.match(mainWorkspace, /其他庫存異動/);
  assert.match(mainWorkspace, /其他庫存操作/);
  assert.doesNotMatch(mainWorkspace, /statusLabels\[row\.status\]\|\|row\.status/);
  assert.doesNotMatch(mainWorkspace, /stateLabels\[row\.status\]\|\|row\.status/);
  assert.doesNotMatch(mainWorkspace, /purchaseStatusLabels\[(?:row|x)\.status\]\|\|(row|x)\.status/);
  assert.doesNotMatch(mainWorkspace, /labels\[row\.status\]\|\|row\.status/);
  assert.doesNotMatch(mainWorkspace, /paymentMethodLabels\[(?:row|x)\.payment_method\]\|\|(row|x)\.payment_method/);
  assert.doesNotMatch(mainWorkspace, /tenderLabels\[payment\.payment_method\]\|\|payment\.payment_method/);
  assert.doesNotMatch(mainWorkspace, /movementTypeLabels\[x\.movement_type\]\|\|x\.movement_type/);
  assert.doesNotMatch(mainWorkspace, /labels\[x\.location_type\]\|\|x\.location_type/);
  assert.doesNotMatch(mainWorkspace, /escapeHtml\(row\.payment_method\)/);
});
