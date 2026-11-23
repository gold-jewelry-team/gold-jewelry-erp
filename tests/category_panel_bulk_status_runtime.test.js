import assert from "node:assert/strict";
import fs from "node:fs";
import test from "node:test";

const html = fs.readFileSync("app/static/index.html", "utf8");
const start = html.indexOf("const renderShortcuts=category=>");
const end = html.indexOf('renderShortcuts("quote");', start);
assert.ok(start >= 0 && end > start, "missing category shortcut renderer");
const source = html.slice(start, end);

test("bulk panel actions expose an accessible live status", () => {
  assert.ok(source.includes('status.setAttribute("role","status")'), "bulk action status must use status role");
  assert.ok(source.includes('status.setAttribute("aria-live","polite")'), "bulk action status must announce changes politely");
  assert.ok(source.includes('status.setAttribute("aria-atomic","true")'), "screen readers should announce the complete status message");
});

test("expand-all and collapse-all announce their completed category action", () => {
  assert.ok(source.includes('status.textContent="已展開 "+categoryPanels.length+" 個功能區"'), "expand-all must announce the number of expanded panels");
  assert.ok(source.includes('status.textContent="已收合 "+categoryPanels.length+" 個功能區"'), "collapse-all must announce the number of collapsed panels");
  assert.ok(source.includes('status.textContent="可展開或收合本分類功能區"'), "switching category must reset the status hint");
});
