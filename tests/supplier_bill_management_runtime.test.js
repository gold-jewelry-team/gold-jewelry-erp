import assert from "node:assert/strict";
import fs from "node:fs";
import test from "node:test";

const html = fs.readFileSync("app/static/index.html", "utf8");
const router = fs.readFileSync("app/routers/supplier_payables.py", "utf8");

test("unpaid supplier bills support edit and void controls", () => {
  assert.match(html, /data-edit-supplier-bill=/);
  assert.match(html, /data-void-supplier-bill=/);
  assert.ok(html.includes('"/supplier-payables/bills/"+editingSupplierBillId'));
  assert.match(html, /supplier-payables\/bills\/\+editingSupplierBillId/);
  assert.match(router, /@router\.patch\("\/bills\/\{bill_id\}"/);
  assert.match(router, /@router\.post\("\/bills\/\{bill_id\}\/void"/);
});

test("supplier bills with payment allocations cannot be edited or voided", () => {
  assert.match(router, /bill\.status != "OPEN" or bill\.paid_amount != 0/);
  assert.match(html, /Number\(row\.paid_amount\)===0/);
});
