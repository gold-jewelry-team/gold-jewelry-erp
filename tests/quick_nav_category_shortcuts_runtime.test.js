import assert from "node:assert/strict";
import fs from "node:fs";
import test from "node:test";

const html = fs.readFileSync("app/static/index.html", "utf8");

test("quick navigation activates the matching category button", () => {
  const categoryNavigation = html.match(/const activate=categoryId=>[\\s\\S]*?activate\\(activeCategory\\);/)?.[0];
  assert.ok(categoryNavigation, "missing category navigation controller");
  assert.match(
    categoryNavigation,
    /nav\\.querySelector\\('button\\[data-category="'\\+category\\+'"\\]'\\)/
  );
  assert.match(categoryNavigation, /if\\(categoryButton\\)categoryButton\\.click\\(\\)/);
  assert.doesNotMatch(
    categoryNavigation,
    /if\\(category&&category!=="global"\\)activate\\(category\\)/
  );
});

test("category button changes refresh the category shortcut list", () => {
  const shortcutController = html.match(/categoryNav\\.querySelectorAll\\("button\\[data-category\\]"\\)[\\s\\S]*?renderShortcuts\\("quote"\\);/)?.[0];
  assert.ok(shortcutController, "missing category shortcut controller");
  assert.match(shortcutController, /addEventListener\\("click",\\(\\)=>renderShortcuts\\(button\\.dataset\\.category\\)\\)/);
});
