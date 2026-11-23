import assert from "node:assert/strict";
import fs from "node:fs";
import test from "node:test";
import vm from "node:vm";

const html = fs.readFileSync("app/static/index.html", "utf8");
const stopStart = html.indexOf("function stopCameraScanner(){");
assert.notEqual(stopStart, -1, "Scanner cleanup function must exist");
const triggerDeclaration = html.indexOf("\nlet scanTrigger=null;", stopStart);
assert.notEqual(triggerDeclaration, -1, "Scanner trigger state must exist");
const closeStart = html.indexOf("async function closeCameraScanner(){", triggerDeclaration);
assert.notEqual(closeStart, -1, "Scanner close function must exist");
const closeEnd = html.indexOf(
  '\ndocument.addEventListener("keydown",event=>{const modal=$("scanModal")',
  closeStart,
);
assert.notEqual(closeEnd, -1, "Scanner close function must be followed by its keyboard handler");

const source =
  html.slice(stopStart, triggerDeclaration) +
  "\nlet scanTrigger=null;\n" +
  html.slice(closeStart, closeEnd);

function setup({ connected = true, frame = 123, trackCount = 2 } = {}) {
  const stopped = [];
  const cancelled = [];
  const focused = [];
  const trigger = {
    isConnected: connected,
    focus() { focused.push("trigger"); },
  };
  const tracks = Array.from({ length: trackCount }, (_, index) => ({
    stop() { stopped.push(index); },
  }));
  const video = { srcObject: {} };
  const modal = {
    classList: {
      added: [],
      add(name) { this.added.push(name); },
    },
  };
  const context = {
    trigger,
    scanFrameHandle: frame,
    scanStream: { getTracks: () => tracks },
    scanDetector: { detect() {} },
    scanBusy: true,
    cancelAnimationFrame(handle) { cancelled.push(handle); },
    $(id) {
      if (id === "scanVideo") return video;
      if (id === "scanModal") return modal;
      throw new Error("Unexpected element lookup: " + id);
    },
  };

  vm.createContext(context);
  vm.runInContext(source, context);
  vm.runInContext("scanTrigger=trigger", context);

  return { context, trigger, video, modal, stopped, cancelled, focused };
}

test("closing scanner stops resources, hides modal, and restores trigger focus", async () => {
  const ui = setup();
  await ui.context.closeCameraScanner();

  assert.deepEqual(ui.stopped, [0, 1]);
  assert.deepEqual(ui.cancelled, [123]);
  assert.equal(ui.context.scanStream, null);
  assert.equal(ui.context.scanFrameHandle, null);
  assert.equal(ui.video.srcObject, null);
  assert.equal(ui.context.scanDetector, null);
  assert.equal(ui.context.scanBusy, false);
  assert.deepEqual(ui.modal.classList.added, ["hidden"]);
  assert.deepEqual(ui.focused, ["trigger"]);
  assert.equal(vm.runInContext("scanTrigger", ui.context), null);
});

test("closing scanner does not focus a trigger that is no longer connected", async () => {
  const ui = setup({ connected: false });
  await ui.context.closeCameraScanner();

  assert.deepEqual(ui.focused, []);
  assert.equal(vm.runInContext("scanTrigger", ui.context), null);
  assert.deepEqual(ui.modal.classList.added, ["hidden"]);
});

test("repeated close remains safe and restores focus only once", async () => {
  const ui = setup();
  await ui.context.closeCameraScanner();
  await ui.context.closeCameraScanner();

  assert.deepEqual(ui.stopped, [0, 1]);
  assert.deepEqual(ui.cancelled, [123]);
  assert.deepEqual(ui.focused, ["trigger"]);
  assert.deepEqual(ui.modal.classList.added, ["hidden", "hidden"]);
  assert.equal(vm.runInContext("scanTrigger", ui.context), null);
});

test("closing scanner is safe when no trigger or camera resources remain", async () => {
  const ui = setup({ frame: null, trackCount: 0 });
  vm.runInContext("scanTrigger=null", ui.context);
  ui.context.scanStream = null;
  ui.context.scanDetector = null;
  ui.context.scanBusy = false;
  ui.video.srcObject = null;

  await assert.doesNotReject(ui.context.closeCameraScanner());

  assert.deepEqual(ui.stopped, []);
  assert.deepEqual(ui.cancelled, []);
  assert.deepEqual(ui.focused, []);
  assert.equal(ui.video.srcObject, null);
  assert.equal(vm.runInContext("scanTrigger", ui.context), null);
});
