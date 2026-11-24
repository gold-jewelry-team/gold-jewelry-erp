import assert from "node:assert/strict";
import fs from "node:fs";
import test from "node:test";

const html = fs.readFileSync("app/static/index.html", "utf8");
const router = fs.readFileSync("app/routers/company_setup.py", "utf8");

test("company management supports edit, deactivate, reactivate, and inactive filtering", () => {
  assert.match(html, /companyIncludeInactive/);
  assert.match(html, /data-edit-company=/);
  assert.match(html, /data-toggle-company=/);
  assert.match(html, /method:editingCompanyId\?"PATCH":"POST"/);
});

test("site management supports edit and activation controls", () => {
  assert.match(html, /siteIncludeInactive/);
  assert.match(html, /data-edit-site=/);
  assert.match(html, /data-toggle-site=/);
  assert.match(html, /method:editingSiteId\?"PATCH":"POST"/);
});

test("storage locations support edit and activation controls without exposing inactive locations to operations", () => {
  assert.match(html, /locationIncludeInactive/);
  assert.match(html, /data-edit-location=/);
  assert.match(html, /data-toggle-location=/);
  assert.match(html, /const activeLocations=locations\.filter\(x=>x\.is_active\)/);
  assert.match(router, /def _location_has_stock/);
  assert.match(router, /此儲存位置仍有庫存/);
  assert.match(router, /此據點仍有庫存/);
});
