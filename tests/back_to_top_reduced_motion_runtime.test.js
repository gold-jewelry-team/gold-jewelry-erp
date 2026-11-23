import assert from "node:assert/strict";
import fs from "node:fs";
import test from "node:test";

const html = fs.readFileSync("app/static/index.html", "utf8");
const topStart = html.indexOf('const topButton=document.getElementById("backToTop")');
const topEnd = html.indexOf("\n })();", topStart);
assert.ok(topStart >= 0 && topEnd > topStart, "missing back-to-top controller");
const topController = html.slice(topStart, topEnd);
const reducedMotionBehavior = 'window.matchMedia&&window.matchMedia("(prefers-reduced-motion: reduce)").matches?"auto":"smooth"';

test("back-to-top appears after scrolling and initializes its visibility", () => {
  assert.ok(topController.includes("window.scrollY>500"), "button should appear after a meaningful scroll distance");
  assert.ok(topController.includes('window.addEventListener("scroll",updateTopButton,{passive:true})'), "scroll listener should remain passive");
  assert.ok(topController.includes("updateTopButton();"), "initial visibility should be synchronized on page load");
});

test("back-to-top respects the operating system reduced-motion preference", () => {
  assert.ok(topController.includes('window.scrollTo({top:0,behavior:'+reducedMotionBehavior+'})'), "back-to-top should use immediate scrolling when reduced motion is preferred");
});

test("all in-page navigation respects the operating system reduced-motion preference", () => {
  assert.ok(html.includes('item.scrollIntoView({behavior:'+reducedMotionBehavior+',block:"start"})'), "nested section shortcuts should respect reduced motion");
  assert.ok(html.includes('panel.scrollIntoView({behavior:'+reducedMotionBehavior+',block:"start"})'), "panel shortcuts should respect reduced motion");
  assert.ok(html.includes('target.scrollIntoView({behavior:'+reducedMotionBehavior+',block:"start"})'), "home dashboard shortcuts should respect reduced motion");
  assert.doesNotMatch(html, /scrollIntoView\\(\\{behavior:"smooth"/, "no in-page scroll action should force smooth motion");
});
