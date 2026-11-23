import assert from "node:assert/strict";
import fs from "node:fs";
import test from "node:test";
import vm from "node:vm";

const html = fs.readFileSync("app/static/index.html", "utf8");
const start = html.indexOf("async function openCameraScanner(target){");
const end = html.indexOf("\nconst scanHistoryKey", start);
assert.notEqual(start, -1, "Camera scanner startup function must exist");
assert.notEqual(end, -1, "Camera scanner startup function must have a stable boundary");
const source = html.slice(start, end).trim();

function setup({ barcodeDetector = true, mediaDevices = true, formats = ["ean_13"], cameraError = null } = {}) {
  const messages = [];
  const cameraCalls = [];
  const stopped = [];
  const elements = new Map();
  const get = (id) => {
    if (!elements.has(id)) {
      elements.set(id, {
        value: "",
        hidden: false,
        textContent: "",
        srcObject: null,
        focused: false,
        children: [],
        replaceChildren() { this.children = []; },
        focus() { this.focused = true; },
        play: async () => {},
        classList: {
          add(name) { this.added = name; },
          remove(name) { this.removed = name; },
        },
      });
    }
    return elements.get(id);
  };
  class Detector {
    constructor(options) { this.options = options; }
    static async getSupportedFormats() { return formats; }
    async detect() { return []; }
  }
  const context = {
    document: { activeElement: { id: "scan-trigger" } },
    window: barcodeDetector ? { BarcodeDetector: Detector } : {},
    navigator: mediaDevices ? {
      mediaDevices: {
        async getUserMedia(constraints) {
          cameraCalls.push(constraints);
          if (cameraError) throw cameraError;
          return { getTracks: () => [{ stop() { stopped.push(true); } }] };
        },
      },
    } : { mediaDevices: null },
    scanTrigger: null,
    scanTarget: "",
    scanFacingMode: "environment",
    scanFormatMode: "linear",
    scanMultipleMode: "block",
    scanDetector: null,
    scanStream: null,
    scanBusy: false,
    scanFrameHandle: null,
    scannerFormats(supported) {
      const linear = ["ean_13", "ean_8", "upc_a", "upc_e", "code_128", "code_39", "itf", "codabar"];
      const mode = context.scanFormatMode;
      const selected = mode === "qr" ? ["qr_code"] : mode === "both" ? [...linear, "qr_code"] : linear;
      return selected.filter((format) => supported.includes(format));
    },
    stopCameraScanner() {
      stopped.push("cleanup");
      if (context.scanStream) context.scanStream.getTracks().forEach((track) => track.stop());
      context.scanStream = null;
      context.scanDetector = null;
      context.scanBusy = false;
    },
    message(id, text, error) { messages.push({ id, text, error }); },
    requestAnimationFrame(callback) { return 1; },
    $(id) { return get(id); },
  };
  vm.createContext(context);
  vm.runInContext(source, context);
  return { context, get, messages, cameraCalls, stopped };
}

test("unsupported BarcodeDetector explains the fallback without requesting camera access", async () => {
  const ui = setup({ barcodeDetector: false });
  await ui.context.openCameraScanner("sale");
  assert.equal(ui.cameraCalls.length, 0);
  assert.equal(ui.messages.length, 1);
  assert.match(ui.messages[0].text, /外接條碼槍或手動輸入/);
  assert.equal(ui.messages[0].error, true);
});

test("missing getUserMedia explains the HTTPS and camera permission requirement", async () => {
  const ui = setup({ mediaDevices: false });
  await ui.context.openCameraScanner("purchase");
  assert.equal(ui.cameraCalls.length, 0);
  assert.equal(ui.messages.length, 1);
  assert.match(ui.messages[0].text, /HTTPS/);
  assert.equal(ui.messages[0].error, true);
});

test("unsupported barcode formats close startup cleanly and show a useful error", async () => {
  const ui = setup({ formats: ["qr_code"] });
  await ui.context.openCameraScanner("quote");
  assert.equal(ui.cameraCalls.length, 0);
  assert.equal(ui.get("scanModal").classList.added, "hidden");
  assert.equal(ui.context.scanDetector, null);
  assert.equal(ui.messages.length, 1);
  assert.match(ui.messages[0].text, /不支援所選的條碼格式/);
});

test("camera permission rejection cleans up and reports the browser error", async () => {
  const ui = setup({ cameraError: new Error("NotAllowedError: Permission denied") });
  await ui.context.openCameraScanner("sale");
  assert.equal(ui.cameraCalls.length, 1);
  assert.equal(ui.get("scanModal").classList.added, "hidden");
  assert.equal(ui.context.scanStream, null);
  assert.equal(ui.context.scanDetector, null);
  assert.equal(ui.messages.length, 1);
  assert.match(ui.messages[0].text, /Permission denied/);
  assert.equal(ui.messages[0].error, true);
});
