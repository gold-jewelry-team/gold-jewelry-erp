import assert from "node:assert/strict";
import fs from "node:fs";
import vm from "node:vm";
import test from "node:test";

const html = fs.readFileSync("app/static/banking.html", "utf8");
const match = html.match(/function clearRejectedBankOperationKey\(storageKey,error\)\s*\{[\s\S]*?\n\}/);
assert.ok(match, "bank retry cleanup helper must exist");

function callCleanup(status) {
  const values = new Map([["pending", JSON.stringify({ key: "same-request" })]]);
  const context = {
    localStorage: {
      getItem: key => values.get(key) ?? null,
      setItem: (key, value) => values.set(key, value),
      removeItem: key => values.delete(key),
    },
  };
  vm.runInNewContext(match[0], context);
  context.clearRejectedBankOperationKey("pending", status === undefined ? {} : { status });
  return values.has("pending");
}

test("HTTP 409 keeps the unresolved bank request for reconciliation", () => {
  assert.equal(callCleanup(409), true);
});

test("only a definitive HTTP 422 validation failure clears the pending request", () => {
  assert.equal(callCleanup(422), false);
});

test("authentication, server and network failures do not discard the pending request", () => {
  assert.equal(callCleanup(401), true);
  assert.equal(callCleanup(500), true);
  assert.equal(callCleanup(undefined), true);
});
