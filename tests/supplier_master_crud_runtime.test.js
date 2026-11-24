import assert from "node:assert/strict";
import fs from "node:fs";
import test from "node:test";

const html = fs.readFileSync("app/static/index.html", "utf8");
const router = fs.readFileSync("app/routers/suppliers.py", "utf8");
const schema = fs.readFileSync("app/routers/schemas/purchasing.py", "utf8");

test("supplier editor supports create and update without changing the company scope", () => {
  assert.match(html, /data-edit-supplier=/);
  assert.match(html, /method:editingSupplierId\?"PATCH":"POST"/);
  assert.match(html, /\/companies\/\+companyId\+"\/suppliers"\+\(editingSupplierId\?/);
  assert.match(schema, /class SupplierUpdate[\s\S]*?is_active: bool \| None = None/);
});

test("supplier list can include inactive rows while operational selectors remain active-only", () => {
  assert.match(html, /supplierIncludeInactive/);
  assert.match(html, /include_inactive=true/);
  assert.match(html, /const activeRows=rows\.filter\(x=>x\.is_active\)/);
  assert.match(html, /const options=activeRows\.map/);
  assert.match(html, /重新啟用/);
  assert.match(html, /停用/);
});

test("supplier activation updates reject null and retain the dedicated deactivate endpoint", () => {
  assert.match(router, /if "is_active" in changes and changes\["is_active"\] is None/);
  assert.match(router, /@router\.post\("\/\{supplier_id\}\/deactivate"/);
});
