import assert from "node:assert/strict";
import fs from "node:fs";
import test from "node:test";
import vm from "node:vm";

const html = fs.readFileSync("app/static/index.html", "utf8");
const start = html.indexOf("let pendingLabelProduct=null;");
assert.notEqual(start, -1, "Label dialog pending state must exist");
const endMarker = "\nfunction renderLabelLotDetails(){";
const end = html.indexOf(endMarker, start);
assert.notEqual(end, -1, "Label dialog close function must be followed by its renderer");
const source = html.slice(start, end);

function setup({ connected = true } = {}) {
  const focusEvents = [];
  const trigger = {
    isConnected: connected,
    focus() { focusEvents.push("restored"); },
  };
  const modal = {
    classList: {
      added: [],
      add(name) { this.added.push(name); },
    },
  };
  const context = {
    trigger,
    modal,
    $(id) {
      assert.equal(id, "labelLotModal");
      return modal;
    },
  };
  vm.createContext(context);
  vm.runInContext(source, context);
  vm.runInContext(
    "pendingLabelProduct={id:'product-1'};" +
    "pendingLabelLots=[{id:'lot-1'},{id:'lot-2'}];" +
    "pendingLabelConfig={prefix:'A-'};" +
    "pendingLabelTrigger=trigger;",
    context,
  );
  return { context, trigger, modal, focusEvents };
}

test("closing label dialog clears pending data and restores trigger focus", () => {
  const ui = setup();
  ui.context.closeLabelLotModal();

  assert.deepEqual(ui.modal.classList.added, ["hidden"]);
  assert.deepEqual(ui.focusEvents, ["restored"]);
  assert.equal(vm.runInContext("pendingLabelProduct", ui.context), null);
  assert.deepEqual(Array.from(vm.runInContext("pendingLabelLots", ui.context)), []);
  assert.equal(vm.runInContext("pendingLabelConfig", ui.context), null);
  assert.equal(vm.runInContext("pendingLabelTrigger", ui.context), null);
});

test("closing label dialog does not focus a trigger removed from the page", () => {
  const ui = setup({ connected: false });
  ui.context.closeLabelLotModal();

  assert.deepEqual(ui.modal.classList.added, ["hidden"]);
  assert.deepEqual(ui.focusEvents, []);
  assert.equal(vm.runInContext("pendingLabelTrigger", ui.context), null);
});

test("repeated label dialog close is idempotent and restores focus once", () => {
  const ui = setup();
  ui.context.closeLabelLotModal();
  ui.context.closeLabelLotModal();

  assert.deepEqual(ui.modal.classList.added, ["hidden", "hidden"]);
  assert.deepEqual(ui.focusEvents, ["restored"]);
  assert.equal(vm.runInContext("pendingLabelProduct", ui.context), null);
  assert.deepEqual(Array.from(vm.runInContext("pendingLabelLots", ui.context)), []);
  assert.equal(vm.runInContext("pendingLabelConfig", ui.context), null);
  assert.equal(vm.runInContext("pendingLabelTrigger", ui.context), null);
});

test("closing label dialog without a pending trigger safely clears state", () => {
  const ui = setup();
  vm.runInContext("pendingLabelTrigger=null", ui.context);

  assert.doesNotThrow(() => ui.context.closeLabelLotModal());

  assert.deepEqual(ui.modal.classList.added, ["hidden"]);
  assert.deepEqual(ui.focusEvents, []);
  assert.equal(vm.runInContext("pendingLabelProduct", ui.context), null);
  assert.deepEqual(Array.from(vm.runInContext("pendingLabelLots", ui.context)), []);
  assert.equal(vm.runInContext("pendingLabelConfig", ui.context), null);
});
