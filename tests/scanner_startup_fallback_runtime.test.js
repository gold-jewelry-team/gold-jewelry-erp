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
        firstElementChild: null,
        attributes: {},
        replaceChildren() { this.children = []; this.firstElementChild = null; },
        appendChild(child) { this.children.push(child); this.firstElementChild = child; },
        setAttribute(name, value) { this.attributes[name] = value; },
        focus() { this.focused = true; },
        play: async () => {},
        classList: {
          added: "",
          removed: [],
          classes: new Set(),
          add(name) { this.added = name; this.classes.add(name); },
          remove(...names) { this.removed.push(...names); names.forEach(name => this.classes.delete(name)); },
          contains(name) { return this.classes.has(name); },
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
    document: {
      activeElement: { id: "scan-trigger" },
      querySelector(selector) {
        assert.equal(selector, ".bunny-shop-note .bunny-art");
        return {
          cloneNode() {
            return {
              className: "",
              attributes: {},
              setAttribute(name, value) { this.attributes[name] = value; },
            };
          },
        };
      },
    },
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
    renderScanHistory() { context.historyRendered = (context.historyRendered || 0) + 1; },
    $(id) { return get(id); },
  };
  const feedbackStart = html.indexOf("function ensureScanFeedbackBunny(){");
  const feedbackEnd = html.indexOf("\\nasync function copyLastScannedCode", feedbackStart);
  assert.notEqual(feedbackStart, -1, "Rabbit scanner feedback helpers must exist");
  assert.notEqual(feedbackEnd, -1, "Rabbit scanner feedback helpers must have a stable boundary");
  const feedbackSource = html.slice(feedbackStart, feedbackEnd);
  vm.createContext(context);
  vm.runInContext('let lastScannedCode="",lastScannedTarget="";', context);
  vm.runInContext(feedbackSource, context);
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
  assert.equal(ui.get("scanFeedbackTitle").textContent, "目前無法使用相機掃描");
  assert.equal(ui.get("scanFeedback").classList.contains("warning"), true);
  assert.equal(ui.get("scanFeedback").classList.contains("hidden"), false);
  assert.equal(ui.get("scanFeedbackBunny").children.length, 1);
  assert.equal(ui.get("scanFeedbackCode").hidden, true);
  assert.equal(ui.get("copyScannedCode").hidden, true);
  assert.equal(ui.context.historyRendered, 1);
});

test("missing getUserMedia explains the HTTPS and camera permission requirement", async () => {
  const ui = setup({ mediaDevices: false });
  await ui.context.openCameraScanner("purchase");
  assert.equal(ui.cameraCalls.length, 0);
  assert.equal(ui.messages.length, 1);
  assert.match(ui.messages[0].text, /HTTPS/);
  assert.equal(ui.messages[0].error, true);
  assert.equal(ui.get("scanFeedbackTitle").textContent, "相機權限尚未就緒");
  assert.equal(ui.get("scanFeedback").classList.contains("warning"), true);
  assert.equal(ui.get("scanFeedbackBunny").children.length, 1);
  assert.equal(ui.get("scanFeedbackCode").hidden, true);
  assert.equal(ui.get("manualLookupCode").hidden, true);
});

test("unsupported barcode formats close startup cleanly and show a useful error", async () => {
  const ui = setup({ formats: ["qr_code"] });
  await ui.context.openCameraScanner("quote");
  assert.equal(ui.cameraCalls.length, 0);
  assert.equal(ui.get("scanModal").classList.added, "hidden");
  assert.equal(ui.context.scanDetector, null);
  assert.equal(ui.messages.length, 1);
  assert.match(ui.messages[0].text, /不支援所選的條碼格式/);
  assert.equal(ui.get("scanFeedbackTitle").textContent, "相機掃描無法啟動");
  assert.equal(ui.get("scanFeedback").classList.contains("error"), true);
  assert.equal(ui.get("scanFeedbackBunny").children.length, 1);
  assert.equal(ui.get("scanFeedbackCode").hidden, true);
});

test("camera permission rejection cleans up and reports the browser error", async () => {
  const permissionError = new Error("Permission denied");
  permissionError.name = "NotAllowedError";
  const ui = setup({ cameraError: permissionError });
  await ui.context.openCameraScanner("sale");
  assert.equal(ui.cameraCalls.length, 1);
  assert.equal(ui.get("scanModal").classList.added, "hidden");
  assert.equal(ui.context.scanStream, null);
  assert.equal(ui.context.scanDetector, null);
  assert.equal(ui.messages.length, 1);
  assert.match(ui.messages[0].text, /尚未授權相機/);
  assert.equal(ui.messages[0].error, true);
  assert.equal(ui.get("scanFeedbackTitle").textContent, "相機掃描無法啟動");
  assert.equal(ui.get("scanFeedback").classList.contains("warning"), true);
  assert.equal(ui.get("scanFeedbackBunny").children.length, 1);
  assert.equal(ui.get("scanFeedbackCode").hidden, true);
});
