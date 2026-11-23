import assert from "node:assert/strict";
import fs from "node:fs";
import test from "node:test";
import vm from "node:vm";

const html = fs.readFileSync("app/static/index.html", "utf8");

function extractHandler(marker) {
  const start = html.indexOf(marker);
  assert.notEqual(start, -1, `Missing keyboard handler: ${marker}`);
  const end = html.indexOf("});", start);
  assert.notEqual(end, -1, "Keyboard handler is not closed");
  return html.slice(start, end + 3);
}

function setup(kind, options = {}) {
  const focusable = [];
  const document = { activeElement: null, handler: null };
  const dialog = {
    focused: false,
    focus() { this.focused = true; document.activeElement = this; },
    querySelectorAll() { return focusable; },
    contains(element) { return focusable.includes(element) || element === this; },
  };
  const modal = {
    classList: { contains: () => !!options.hidden },
    querySelector(selector) {
      assert.equal(selector, kind === "scanner" ? ".scan-dialog" : ".label-lot-dialog");
      return dialog;
    },
  };
  for (let i = 0; i < (options.count ?? 2); i += 1) {
    const element = {
      focused: false,
      focus() { this.focused = true; document.activeElement = this; },
      getClientRects() { return [{}]; },
    };
    focusable.push(element);
  }
  const context = {
    document,
    $(id) { return id === (kind === "scanner" ? "scanModal" : "labelLotModal") ? modal : null; },
    closeCameraScanner() { context.closed = "scanner"; },
    closeLabelLotModal() { context.closed = "label"; },
    closed: null,
  };
  vm.createContext(context);
  const marker = kind === "scanner"
    ? 'document.addEventListener("keydown",event=>{const modal=$("scanModal")'
    : 'document.addEventListener("keydown",event=>{const modal=$("labelLotModal")';
  vm.runInContext(extractHandler(marker), context);
  return { context, document, dialog, modal, focusable, fire(key, shiftKey = false) {
    let prevented = false;
    document.handler({ key, shiftKey, preventDefault() { prevented = true; } });
    return prevented;
  }};
}

// Both dialogs must keep keyboard navigation inside their own focusable controls.
for (const kind of ["scanner", "label"]) {
  test(`${kind}: Tab from the last control wraps to the first`, () => {
    const ui = setup(kind);
    ui.document.activeElement = ui.focusable.at(-1);
    assert.equal(ui.fire("Tab"), true);
    assert.equal(ui.document.activeElement, ui.focusable[0]);
  });

  test(`${kind}: Shift+Tab from the first control wraps to the last`, () => {
    const ui = setup(kind);
    ui.document.activeElement = ui.focusable[0];
    assert.equal(ui.fire("Tab", true), true);
    assert.equal(ui.document.activeElement, ui.focusable.at(-1));
  });

  test(`${kind}: focus outside the dialog is redirected to the correct edge`, () => {
    const ui = setup(kind);
    ui.document.activeElement = { outside: true };
    assert.equal(ui.fire("Tab"), true);
    assert.equal(ui.document.activeElement, ui.focusable[0]);
    ui.document.activeElement = { outside: true };
    assert.equal(ui.fire("Tab", true), true);
    assert.equal(ui.document.activeElement, ui.focusable.at(-1));
  });

  test(`${kind}: an empty dialog focuses its dialog container`, () => {
    const ui = setup(kind, { count: 0 });
    assert.equal(ui.fire("Tab"), true);
    assert.equal(ui.dialog.focused, true);
    assert.equal(ui.document.activeElement, ui.dialog);
  });

  test(`${kind}: Escape closes the dialog and prevents browser default`, () => {
    const ui = setup(kind);
    assert.equal(ui.fire("Escape"), true);
    assert.equal(ui.context.closed, kind);
  });

  test(`${kind}: a hidden dialog does not intercept keyboard input`, () => {
    const ui = setup(kind, { hidden: true });
    assert.equal(ui.fire("Tab"), false);
    assert.equal(ui.document.activeElement, null);
  });
}
