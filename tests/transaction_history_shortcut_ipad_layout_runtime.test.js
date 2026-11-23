import assert from "node:assert/strict";
import fs from "node:fs";
import test from "node:test";

const html = fs.readFileSync("app/static/index.html", "utf8");

test("transaction history home shortcut resolves its nested sales panel and remains actionable", () => {
  assert.match(html, /data-home-target="salesHistoryPanel"/);
  assert.match(html, /id="salesHistoryPanel"/);
  assert.match(html, /\["salesPanel","salePaymentPanel","saleReturnPanel","returnPaymentPanel"\].*?"sales"/s);
  const start = html.indexOf('document.addEventListener("click",function(event){', html.indexOf("/* 首頁快捷卡片"));
  const end = html.indexOf("\n});", start);
  assert.ok(start >= 0 && end > start, "missing home shortcut click handler");
  const handler = html.slice(start, end);
  assert.ok(handler.includes('event.target instanceof Element?event.target:event.target&&event.target.parentElement'), "non-Element event targets must be handled safely");
  assert.ok(handler.includes('target.closest("section.panel[data-category]")'), "nested history section must resolve its owning sales category");
  assert.ok(handler.includes('window.requestAnimationFrame(()=>window.requestAnimationFrame(()=>{'), "nested target must wait for category visibility/layout before scrolling");
  assert.ok(handler.includes('target.scrollIntoView({behavior:'), "history shortcut must scroll to its target");
  assert.ok(handler.includes('target.focus({preventScroll:true})'), "history shortcut must move focus to its target");
});

test("iPad portrait dashboard and work panels use the available tablet width", () => {
  const tabletRule = html.match(/@media\(min-width:640px\) and \(max-width:899px\)\{\s*main\{width:100%;max-width:none;padding:16px 20px\}\s*#homeDashboard\{width:100%;grid-column:1\/-1\}\s*\}/);
  assert.ok(tabletRule, "tablet layout should remove the narrow 760px main width cap");
});
