import assert from "node:assert/strict";
import fs from "node:fs";
import test from "node:test";

const html = fs.readFileSync("app/static/index.html", "utf8");
const desktopPanelOffset = "main>section.panel[id]{scroll-margin-top:240px}";
const desktopHeadingOffset = "main>section.panel[id] h3{scroll-margin-top:240px}";
const mobileRule = html.match(/@media\(max-width:899px\)\{header\{position:static;top:auto\}\.category-shortcuts\{position:static;top:auto;max-height:none;overflow:visible;z-index:auto\}([^}]*)\}/);

test("desktop panel and nested heading targets account for sticky navigation", () => {
  assert.ok(html.includes(desktopPanelOffset), "desktop panel offset must remain compatible with sticky header");
  assert.ok(html.includes(desktopHeadingOffset), "nested section headings need a desktop scroll offset too");
});

test("mobile scroll targets use a compact offset when the header is not sticky", () => {
  assert.ok(mobileRule, "mobile header and shortcut layout override must exist");
  assert.ok(
    mobileRule[1].includes("main>section.panel[id],main>section.panel[id] h3{scroll-margin-top:24px"),
    "mobile panel and nested heading targets should not reserve the desktop 240px header gap"
  );
});

test("back-to-top remains reachable above the device safe area", () => {
  assert.match(html, /#backToTop\{[^}]*min-height:44px/);
  assert.match(html, /#backToTop\{[^}]*bottom:calc\(18px \+ env\(safe-area-inset-bottom\)\)/);
  assert.match(html, /id="backToTop"[^>]*aria-label="回到頁面頂端"/);
});
