import assert from "node:assert/strict";
import fs from "node:fs";
import test from "node:test";

const html = fs.readFileSync("app/static/index.html", "utf8");
const start = html.indexOf('const getNavigationScrollBehavior=()');
const end = html.indexOf('(function(){\n const nav=document.getElementById("quickNav");', start);
assert.ok(start >= 0 && end > start, "missing back-to-top controller");
const controller = html.slice(start, end);

test("back-to-top appears after scrolling and initializes its visibility", () => {
  assert.ok(controller.includes("window.scrollY>500"), "button should appear after a meaningful scroll distance");
  assert.ok(controller.includes('window.addEventListener("scroll",updateTopButton,{passive:true})'), "scroll listener should remain passive");
  assert.ok(controller.includes("updateTopButton();"), "initial visibility should be synchronized on page load");
});

test("back-to-top respects the operating system reduced-motion preference", () => {
  assert.ok(
    controller.includes('window.matchMedia&&window.matchMedia("(prefers-reduced-motion: reduce)").matches?"auto":"smooth"'),
    "reduced-motion users should get an immediate scroll instead of forced smooth animation"
  );
  assert.ok(controller.includes('window.scrollTo({top:0,behavior:getNavigationScrollBehavior()})'), "back-to-top should continue to scroll to the page origin");
});

test("all in-page navigation uses the shared reduced-motion-aware behavior", () => {
  assert.ok(controller.includes('item.scrollIntoView({behavior:getNavigationScrollBehavior(),block:"start"})'), "nested section shortcuts should respect reduced motion");
  assert.ok(controller.includes('panel.scrollIntoView({behavior:getNavigationScrollBehavior(),block:"start"})'), "category and panel shortcuts should respect reduced motion");
  assert.ok(controller.includes('target.scrollIntoView({behavior:getNavigationScrollBehavior(),block:"start"})'), "home dashboard shortcuts should respect reduced motion");
  assert.doesNotMatch(html, /scrollIntoView\\(\\{behavior:"smooth"/, "no in-page scroll action should force smooth motion");
});
