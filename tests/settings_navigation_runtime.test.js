import assert from "node:assert/strict";
import fs from "node:fs";
import test from "node:test";

const html = fs.readFileSync("app/static/index.html", "utf8");
const start = html.indexOf('/* 分類內快速定位：避免長頁面反覆捲動 */');
const end = html.indexOf('const quickButton=document.getElementById("quickGoldPrice");', start);
assert.ok(start >= 0 && end > start, "missing category shortcut and settings search controller");
const controller = html.slice(start, end);

test("settings category provides a labelled search field", () => {
  assert.match(controller, /search\.type="search"/);
  assert.match(controller, /search\.setAttribute\("aria-label","搜尋設定功能"\)/);
  assert.match(controller, /search\.placeholder="搜尋設定功能/);
  assert.match(controller, /search\.hidden=category!=="settings"/);
});

test("settings search matches section headings and field labels without changing other categories", () => {
  assert.match(controller, /\[titleFor\(panel\),\.\.\.subTitlesOf\(panel\),panel\.textContent\|\|""\]/);
  assert.match(controller, /panel\.dataset\.category==="settings"/);
  assert.match(controller, /panel\.style\.display=match\?"":"none"/);
  assert.match(controller, /const button=settingsButtons\.get\(panel\)/);
});

test("settings panels start collapsed and are expanded only when selected", () => {
  assert.match(controller, /shortcuts\.classList\.toggle\("settings-mode",category==="settings"\)/);
  assert.match(controller, /if\(category==="settings"&&!panel\.classList\.contains\("panel-collapsed"\)\)/);
  assert.match(controller, /if\(panel\.classList\.contains\("panel-collapsed"\)\)[\s\S]*?toggle\.click\(\)/);
});

test("mobile settings search wraps into a readable full-width row", () => {
  assert.match(html, /\.category-shortcuts\.settings-mode\{flex-wrap:wrap;overflow:visible;white-space:normal\}/);
  assert.match(html, /\.category-shortcuts\.settings-mode \.category-settings-search\{flex:1 1 100%;width:100%;max-width:none\}/);
});
