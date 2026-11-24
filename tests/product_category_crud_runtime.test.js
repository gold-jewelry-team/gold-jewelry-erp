import assert from "node:assert/strict";
import fs from "node:fs";
import test from "node:test";

const html = fs.readFileSync("app/static/index.html", "utf8");
const router = fs.readFileSync("app/routers/product_master.py", "utf8");
const schema = fs.readFileSync("app/routers/schemas/product_master.py", "utf8");

test("category manager supports edit, inactive visibility, and reactivation", () => {
  assert.match(html, /data-edit-category=/);
  assert.match(html, /data-toggle-category=/);
  assert.match(html, /categoryIncludeInactive/);
  assert.match(html, /include_inactive=true/);
  assert.match(html, /method:editingCategoryId\?"PATCH":"POST"/);
  assert.match(html, /重新啟用/);
});

test("category update API protects company scope and active references", () => {
  assert.match(router, /@router\.patch\([\s\S]*?product-categories\/\{category_id\}/);
  assert.match(router, /ProductCategory\.company_id == company_id/);
  assert.match(router, /Product\.category_id == category_id/);
  assert.match(router, /Product\.is_active\.is_\(True\)/);
  assert.match(router, /active_child/);
  assert.match(router, /分類不可設定自己為上層分類/);
  assert.match(schema, /class ProductCategoryUpdate/);
});
