import assert from "node:assert/strict";
import fs from "node:fs";
import test from "node:test";

const html = fs.readFileSync("app/static/index.html", "utf8");

test("every home dashboard shortcut points to one existing unique section", () => {
  const ids = [...html.matchAll(/\bid="([^"]+)"/g)].map((match) => match[1]);
  const targets = [...html.matchAll(/data-home-target="([^"]+)"/g)].map((match) => match[1]);

  assert.ok(targets.length > 0, "home dashboard must expose shortcut targets");
  for (const target of new Set(targets)) {
    assert.ok(ids.includes(target), `home shortcut target does not exist: ${target}`);
    assert.equal(ids.filter((id) => id === target).length, 1, `home shortcut target must be unique: ${target}`);
  }
});

test("home dashboard shortcuts activate, expand, scroll to and focus their target", () => {
  const start = html.indexOf('document.addEventListener("click",function(event){', html.indexOf("/* 首頁快捷卡片"));
  const end = html.indexOf("\n});", start);
  assert.ok(start >= 0 && end > start, "missing home shortcut click handler");
  const handler = html.slice(start, end);

  assert.ok(handler.includes('event.target.closest("[data-home-target]")'), "nested shortcut content must resolve to its parent action");
  assert.ok(handler.includes('document.getElementById(shortcut.getAttribute("data-home-target"))'), "shortcut must resolve its section by ID");
  assert.ok(handler.includes('categoryButton.click()'), "shortcut must activate the target category through the category button");
  assert.ok(handler.includes('target.querySelector(":scope > h2 .panel-toggle")'), "collapsed target panels must be expanded");
  assert.ok(handler.includes('target.scrollIntoView({behavior:"smooth",block:"start"})'), "shortcut must scroll to its target");
  assert.ok(handler.includes('target.focus({preventScroll:true})'), "shortcut must move keyboard focus to its target");
});
