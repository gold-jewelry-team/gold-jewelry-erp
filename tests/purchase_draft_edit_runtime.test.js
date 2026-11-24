import assert from "node:assert/strict";
import fs from "node:fs";
import test from "node:test";

const html = fs.readFileSync("app/static/index.html", "utf8");
const router = fs.readFileSync("app/routers/purchases.py", "utf8");
const service = fs.readFileSync("app/services/purchasing.py", "utf8");

test("draft purchase rows can be edited and the editor supports update and cancel", () => {
  assert.match(html, /data-edit-purchase=/);
  assert.match(html, /editingPurchaseId/);
  assert.match(html, /method:editingPurchaseId\?"PATCH":"POST"/);
  assert.match(html, /cancelPurchaseEdit/);
  assert.match(html, /row\.status==="DRAFT"/);
  assert.match(router, /@router\.patch\("\/{purchase_id}"/);
});

test("purchase drafts with valid supplier bills are protected and only drafts can be updated", () => {
  assert.match(service, /if purchase\.status != "DRAFT"/);
  assert.match(service, /SupplierBill\.purchase_id == purchase_id/);
  assert.match(service, /status != "VOID"/);
  assert.match(service, /不可新增停用中的商品至採購草稿/);
});
