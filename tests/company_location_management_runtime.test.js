import assert from "node:assert/strict";
import fs from "node:fs";
import test from "node:test";

const html = fs.readFileSync("app/static/index.html", "utf8");
const router = fs.readFileSync("app/routers/company_setup.py", "utf8");

test("company management supports edit and inactive visibility", () => {
  assert.match(html, /companyIncludeInactive/);
  assert.match(html, /data-edit-company=/);
  assert.match(html, /data-toggle-company=/);
  assert.match(html, /\/companies"\+\(editingCompanyId\?/);
});

test("site and storage location management support edit and status changes", () => {
  assert.match(html, /siteIncludeInactive/);
  assert.match(html, /data-edit-site=/);
  assert.match(html, /data-toggle-site=/);
  assert.match(html, /locationIncludeInactive/);
  assert.match(html, /data-edit-location=/);
  assert.match(html, /data-toggle-location=/);
});

test("storage location deactivation is blocked while any product balance remains", () => {
  assert.match(router, /def _location_has_stock/);
  assert.match(router, /if _location_has_stock\(db, company_id, site_id, location_id\)/);
  assert.match(router, /此儲存位置仍有庫存/);
  assert.match(router, /此據點仍有庫存/);
});
