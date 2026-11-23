import assert from "node:assert/strict";
import fs from "node:fs";
import test from "node:test";

const html = fs.readFileSync("app/static/index.html", "utf8");

test("desktop dashboard spans both columns before the navigation layout", () => {
  assert.match(html, /<main>\s*<section id="homeDashboard"/);
  const desktop = html.match(/@media\(min-width:900px\)\{([\s\S]*?)\n\}/)?.[1];
  assert.ok(desktop, "missing desktop two-column layout");
  assert.match(desktop, /#homeDashboard\s*\{\s*grid-column:1\/-1\s*\}/);
  assert.match(desktop, /\.category-nav\s*\{[^}]*grid-row:2\s*\/\s*span 50/);
});

test("tablet and mobile dashboard layout is not overridden by desktop-only rules", () => {
  const desktopStart = html.indexOf("@media(min-width:900px){");
  assert.notEqual(desktopStart, -1);
  const dashboardRule = html.indexOf("#homeDashboard{grid-column:1/-1}", desktopStart);
  assert.ok(dashboardRule > desktopStart, "dashboard spanning rule must be desktop-only");
});
