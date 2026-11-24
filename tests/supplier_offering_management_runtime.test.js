import assert from "node:assert/strict";
import fs from "node:fs";
import test from "node:test";

const html = fs.readFileSync("app/static/index.html", "utf8");

test("supplier category offerings can be edited and paused or stopped rows can be shown", () => {
  assert.match(html, /data-edit-category-offering=/);
  assert.match(html, /supplierOfferingIncludeInactive/);
  assert.match(html, /supplier-category-offerings\/\+editingSupplierCategoryOfferingId/);
  assert.match(html, /method:"PATCH"/);
  assert.match(html, /supplierCategoryOfferingCancel/);
});

test("supplier product offerings can edit quote details and status", () => {
  assert.match(html, /data-edit-product-offering=/);
  assert.match(html, /supplierProductOfferingIncludeInactive/);
  assert.match(html, /supplier-product-offerings\/\+editingSupplierProductOfferingId/);
  assert.match(html, /quoted_unit_cost/);
  assert.match(html, /supplierProductOfferingCancel/);
});
