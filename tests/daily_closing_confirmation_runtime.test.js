import assert from "node:assert/strict";
import fs from "node:fs";
import test from "node:test";

const html = fs.readFileSync("app/static/index.html", "utf8");
const start = html.indexOf('$("dailyClosingForm").addEventListener("submit"');
const end = html.indexOf('$("cashCountCreateForm").addEventListener("submit"', start);
assert.notEqual(start, -1, "daily closing submit handler must exist");
assert.notEqual(end, -1, "daily closing submit handler must have a stable boundary");
const handler = html.slice(start, end);

test("daily closing clearly warns that the snapshot is permanent", () => {
  assert.match(html, /class="closing-warning" role="note"/);
  assert.match(html, /結帳後不可覆寫/);
  assert.match(html, /同一日期只能結帳一次/);
  assert.match(html, /該日不可再新增銷售或退貨/);
});

test("daily closing requires an explicit confirmation before creating the snapshot", () => {
  assert.match(handler, /if\(!payload\.business_date\)/);
  assert.match(handler, /window\.confirm\(/);
  assert.match(handler, /不可覆寫的結帳快照/);
  assert.match(handler, /確定建立每日結帳/);

  const confirmIndex = handler.indexOf("if(!window.confirm(");
  const requestIndex = handler.indexOf('await api("/companies/"+companyId+"/sites/"+selectedSiteId+"/daily-closings"');
  assert.ok(confirmIndex >= 0, "confirmation must be present");
  assert.ok(requestIndex > confirmIndex, "the API request must happen only after confirmation");
});
