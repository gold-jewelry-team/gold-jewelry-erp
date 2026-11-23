import assert from "node:assert/strict";
import fs from "node:fs";
import test from "node:test";

const html = fs.readFileSync("app/static/index.html", "utf8");

test("quick navigation exposes an accessible no-results message", () => {
  assert.match(
    html,
    /<span id="quickNavEmpty" class="quick-nav-empty" role="status" aria-live="polite" hidden>/
  );
  assert.ok(
    html.includes('if(emptyState)emptyState.hidden=!query||visible>0;'),
    "empty state must appear only for a non-empty query with zero matches"
  );
  assert.ok(
    html.includes(".quick-nav.searching .quick-nav-empty:not([hidden]){display:inline-flex}"),
    "no-results message must be visible while searching"
  );
});
