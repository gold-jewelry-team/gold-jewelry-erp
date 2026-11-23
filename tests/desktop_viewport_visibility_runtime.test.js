import assert from "node:assert/strict";
import fs from "node:fs";
import test from "node:test";

const html = fs.readFileSync("app/static/index.html", "utf8");
const desktopFix = html.match(/\/\* Desktop viewport recovery:[\s\S]*?@media\(min-width:900px\)\{([\s\S]*?)\n\}/)?.[1];

test("desktop header scrolls with the document instead of covering the workspace", () => {
  assert.ok(desktopFix, "desktop viewport recovery rules must exist");
  assert.match(desktopFix, /header\s*\{\s*position:static;top:auto\s*\}/);
});

test("desktop sticky navigation uses compact offsets after the header scrolls away", () => {
  assert.match(desktopFix, /\.category-nav\s*\{\s*top:16px\s*\}/);
  assert.match(desktopFix, /\.category-shortcuts\s*\{\s*top:16px\s*\}/);
  assert.match(desktopFix, /scroll-margin-top:24px/);
});

test("desktop-only viewport recovery does not replace the existing mobile header behavior", () => {
  assert.match(html, /@media\(max-width:899px\)\{header\{position:static;top:auto\}/);
  assert.match(html, /@media\(min-width:900px\)\{[\s\S]*?header\{position:static;top:auto\}/);
});
