import assert from "node:assert/strict";
import fs from "node:fs";
import test from "node:test";

const html = fs.readFileSync("app/static/index.html", "utf8");

test("quick navigation activates the matching category button", () => {
  const start = html.indexOf("const activate=categoryId=>");
  const endMarker = "activate(activeCategory);";
  const end = html.indexOf(endMarker, start);
  assert.ok(start >= 0 && end > start, "missing category navigation controller");
  const categoryNavigation = html.slice(start, end + endMarker.length);
  assert.ok(
    categoryNavigation.includes("nav.querySelector('button[data-category=\"'+category+'\"]')"),
    "quick navigation must find the matching category navigation button"
  );
  assert.ok(
    categoryNavigation.includes("if(categoryButton)categoryButton.click();"),
    "quick navigation must click the category button so all category listeners run"
  );
  assert.ok(
    !categoryNavigation.includes('if(category&&category!=="global")activate(category);'),
    "quick navigation must not bypass category button listeners"
  );
});

test("category button changes refresh the category shortcut list", () => {
  assert.ok(
    html.includes('categoryNav.querySelectorAll("button[data-category]").forEach(button=>{'),
    "missing category shortcut button listener"
  );
  assert.ok(
    html.includes('button.addEventListener("click",()=>renderShortcuts(button.dataset.category));'),
    "category shortcut list must refresh when its category changes"
  );
});
