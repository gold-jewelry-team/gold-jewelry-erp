import assert from "node:assert/strict";
import fs from "node:fs";
import test from "node:test";

const html = fs.readFileSync("app/static/index.html", "utf8");
const start = html.indexOf('buttons.forEach((button,id)=>button.addEventListener("click",event=>{');
const end = html.indexOf("activate(activeCategory);", start);

test("manual desktop category changes reveal the first panel of the selected category", () => {
  assert.ok(start >= 0 && end > start, "category click handler must exist");
  const handler = html.slice(start, end);
  assert.ok(handler.includes("event.isTrusted"), "only real user clicks should trigger category-level scrolling");
  assert.ok(handler.includes('window.matchMedia("(min-width: 900px)").matches'), "scroll anchoring is desktop-only");
  assert.ok(handler.includes("panels.find(panel=>panel.dataset.category===id)"), "the first selected-category panel must be targeted");
  assert.ok(handler.includes('block:"start"'), "the selected category should align to the reading start");
});

test("synthetic category clicks preserve quick-link target scrolling", () => {
  const handler = html.slice(start, end);
  assert.match(handler, /if\(changed&&event\.isTrusted&&window\.matchMedia/);
  assert.ok(handler.includes('window.matchMedia("(prefers-reduced-motion: reduce)").matches?"auto":"smooth"'));
  assert.ok(handler.includes('const changed=id!==activeCategory;'), "reselecting the active category must not jump the page");
});
