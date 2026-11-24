import assert from "node:assert/strict";
import fs from "node:fs";
import test from "node:test";

const html = fs.readFileSync("app/static/index.html", "utf8");
const router = fs.readFileSync("app/routers/sales.py", "utf8");
const service = fs.readFileSync("app/services/sales.py", "utf8");

test("draft sales can be edited from history and saved with PATCH", () => {
  assert.match(html, /data-edit-sale=/);
  assert.match(html, /editingSaleId/);
  assert.ok(html.includes('"/sales"+(editingSaleId?"/"+editingSaleId:"")'));
  assert.match(html, /method:editingSaleId\?"PATCH":"POST"/);
  assert.match(router, /@router\.patch\("\/\{sale_id\}"/);
});

test("only uncompleted drafts can be repriced and their sale identity is preserved", () => {
  assert.match(service, /sale\.status != "DRAFT"/);
  assert.match(service, /sale\.sale_no = sale_no/);
  assert.match(service, /line\.sale = sale/);
  assert.match(html, /已停用或不在目前可用清單的商品／儲位/);
});
