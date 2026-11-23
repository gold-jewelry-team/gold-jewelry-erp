import assert from "node:assert/strict";
import fs from "node:fs";
import test from "node:test";
import vm from "node:vm";

const html = fs.readFileSync("app/static/index.html", "utf8");
const start = html.indexOf("function scannerFormats(supported){");
const end = html.indexOf("\nasync function openCameraScanner", start);
assert.notEqual(start, -1, "Scanner format helper must exist");
assert.notEqual(end, -1, "Scanner detection helpers must have a stable boundary");
const source = html.slice(start, end);

function setup() {
  const closed = [];
  const handled = [];
  const results = {
    hidden: true,
    children: [],
    replaceChildren() { this.children = []; },
    appendChild(child) { this.children.push(child); },
  };
  const hint = { textContent: "" };
  const context = {
    closeCameraScanner: async () => { closed.push(true); },
    handleScannedProductCode: async (code, target) => { handled.push({ code, target }); },
    document: {
      createElement(tag) {
        assert.equal(tag, "button");
        return {
          type: "",
          className: "",
          textContent: "",
          listeners: {},
          addEventListener(name, callback) { this.listeners[name] = callback; },
          click() { return this.listeners.click(); },
        };
      },
    },
    $(id) {
      if (id === "scanResults") return results;
      if (id === "scanHint") return hint;
      throw new Error("Unexpected element lookup: " + id);
    },
  };
  vm.createContext(context);
  vm.runInContext('let scanFormatMode="linear",scanMultipleMode="block",scanBusy=false,scanTarget="sale";', context);
  vm.runInContext(source, context);
  return { context, results, hint, closed, handled };
}

test("linear mode selects supported one-dimensional formats only", () => {
  const ui = setup();
  const formats = ui.context.scannerFormats([
    "qr_code", "ean_13", "code_128", "upc_a", "data_matrix",
  ]);
  assert.deepEqual(Array.from(formats), ["ean_13", "upc_a", "code_128"]);
});

test("QR mode selects QR only when supported", () => {
  const ui = setup();
  vm.runInContext('scanFormatMode="qr"', ui.context);
  assert.deepEqual(Array.from(ui.context.scannerFormats([
    "ean_13", "qr_code", "code_128",
  ])), ["qr_code"]);
  assert.deepEqual(Array.from(ui.context.scannerFormats(["ean_13"])), []);
});

test("combined mode includes supported linear and QR formats without unsupported formats", () => {
  const ui = setup();
  vm.runInContext('scanFormatMode="both"', ui.context);
  assert.deepEqual(Array.from(ui.context.scannerFormats([
    "qr_code", "ean_13", "code_128", "data_matrix",
  ])), ["ean_13", "code_128", "qr_code"]);
});

test("center gate accepts only results inside the defined central scan region", () => {
  const ui = setup();
  const video = { videoWidth: 1000, videoHeight: 800 };
  const item = (x, y) => ({ boundingBox: { x: x - 10, y: y - 10, width: 20, height: 20 } });
  assert.equal(ui.context.scanResultInCenter(item(500, 400), video), true);
  assert.equal(ui.context.scanResultInCenter(item(150, 240), video), true);
  assert.equal(ui.context.scanResultInCenter(item(850, 560), video), true);
  assert.equal(ui.context.scanResultInCenter(item(149, 400), video), false);
  assert.equal(ui.context.scanResultInCenter(item(851, 400), video), false);
  assert.equal(ui.context.scanResultInCenter(item(500, 239), video), false);
  assert.equal(ui.context.scanResultInCenter(item(500, 561), video), false);
  assert.equal(ui.context.scanResultInCenter({}, video), false);
  assert.equal(ui.context.scanResultInCenter(item(500, 400), { videoWidth: 0, videoHeight: 800 }), false);
});

test("multiple results are presented as explicit choices and no item is auto-selected", () => {
  const ui = setup();
  ui.context.showScanChoices([
    { rawValue: "471000000001", format: "ean_13" },
    { rawValue: "PRODUCT-QR-002", format: "qr_code" },
  ]);
  assert.equal(ui.results.hidden, false);
  assert.equal(ui.results.children.length, 2);
  assert.equal(ui.results.children[0].textContent, "一維條碼：471000000001");
  assert.equal(ui.results.children[1].textContent, "QR Code：PRODUCT-QR-002");
  assert.equal(vm.runInContext("scanBusy", ui.context), true);
  assert.match(ui.hint.textContent, /請選擇正確的商品碼/);
  assert.deepEqual(ui.closed, []);
  assert.deepEqual(ui.handled, []);
});

test("choosing one detected result trims its value and routes it to the original target", async () => {
  const ui = setup();
  ui.context.showScanChoices([
    { rawValue: "471000000001", format: "ean_13" },
    { rawValue: "PRODUCT-QR-002", format: "qr_code" },
  ]);
  await ui.results.children[1].click();
  assert.deepEqual(ui.closed, [true]);
  assert.deepEqual(ui.handled, [{ code: "PRODUCT-QR-002", target: "sale" }]);
});

test("empty scan values do not close the camera or trigger product lookup", async () => {
  const ui = setup();
  await ui.context.chooseScannedCode({ rawValue: "   " });
  assert.deepEqual(ui.closed, []);
  assert.deepEqual(ui.handled, []);
});


test("keyboard scanner submits trimmed values when the suffix is Enter", () => {
  const ui = setup();
  const calls = [];
  let prevented = false;
  const event = { key: "Enter", preventDefault() { prevented = true; } };
  assert.equal(ui.context.handleKeyboardScannerInput(event, " 471000000001 ", code => calls.push(code)), true);
  assert.equal(prevented, true);
  assert.deepEqual(calls, ["471000000001"]);
});

test("keyboard scanner submits trimmed values when the suffix is Tab", () => {
  const ui = setup();
  const calls = [];
  let prevented = false;
  const event = { key: "Tab", preventDefault() { prevented = true; } };
  assert.equal(ui.context.handleKeyboardScannerInput(event, " PRODUCT-QR-002\t", code => calls.push(code)), true);
  assert.equal(prevented, true);
  assert.deepEqual(calls, ["PRODUCT-QR-002"]);
});

test("empty keyboard scanner values preserve normal Tab navigation", () => {
  const ui = setup();
  let prevented = false;
  const event = { key: "Tab", preventDefault() { prevented = true; } };
  assert.equal(ui.context.handleKeyboardScannerInput(event, "   ", () => assert.fail("must not submit")), false);
  assert.equal(prevented, false);
});

test("ordinary keyboard keys do not submit or block input", () => {
  const ui = setup();
  let prevented = false;
  const event = { key: "a", preventDefault() { prevented = true; } };
  assert.equal(ui.context.handleKeyboardScannerInput(event, "ABC", () => assert.fail("must not submit")), false);
  assert.equal(prevented, false);
});
