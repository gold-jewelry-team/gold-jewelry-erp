import assert from "node:assert/strict";
import fs from "node:fs";
import test from "node:test";
import vm from "node:vm";

const html = fs.readFileSync("app/static/index.html", "utf8");
const start = html.indexOf("function stopCameraScanner(){");
assert.notEqual(start, -1, "Scanner cleanup function must exist");
const end = html.indexOf("\n}", start);
assert.notEqual(end, -1, "Scanner cleanup function must close");
const source = html.slice(start, end + 2);

function setup({ frame = 42, tracks = 2, stream = true } = {}) {
  const stopped = [];
  const cancelled = [];
  const video = { srcObject: stream ? {} : null };
  const trackList = Array.from({ length: tracks }, (_, index) => ({
    stop() { stopped.push(index); },
  }));
  const context = {
    scanFrameHandle: frame,
    scanStream: stream ? { getTracks: () => trackList } : null,
    scanDetector: { detect() {} },
    scanBusy: true,
    cancelAnimationFrame(handle) { cancelled.push(handle); },
    $(id) { assert.equal(id, "scanVideo"); return video; },
  };
  vm.createContext(context);
  vm.runInContext(source, context);
  return { context, video, stopped, cancelled };
}

test("stops every camera track and clears the stream reference", () => {
  const ui = setup({ tracks: 3 });
  ui.context.stopCameraScanner();
  assert.deepEqual(ui.stopped, [0, 1, 2]);
  assert.equal(ui.context.scanStream, null);
  assert.equal(ui.video.srcObject, null);
});

test("cancels the pending animation frame and clears its handle", () => {
  const ui = setup({ frame: 123 });
  ui.context.stopCameraScanner();
  assert.deepEqual(ui.cancelled, [123]);
  assert.equal(ui.context.scanFrameHandle, null);
});

test("resets detector and busy state after cleanup", () => {
  const ui = setup();
  ui.context.stopCameraScanner();
  assert.equal(ui.context.scanDetector, null);
  assert.equal(ui.context.scanBusy, false);
});

test("cleanup is safe when no camera stream or animation is active", () => {
  const ui = setup({ frame: null, stream: false, tracks: 0 });
  assert.doesNotThrow(() => ui.context.stopCameraScanner());
  assert.deepEqual(ui.cancelled, []);
  assert.deepEqual(ui.stopped, []);
  assert.equal(ui.video.srcObject, null);
  assert.equal(ui.context.scanDetector, null);
  assert.equal(ui.context.scanBusy, false);
});

test("repeated cleanup does not stop tracks or cancel frames twice", () => {
  const ui = setup({ frame: 123, tracks: 2 });
  ui.context.stopCameraScanner();
  ui.context.stopCameraScanner();

  assert.deepEqual(ui.stopped, [0, 1]);
  assert.deepEqual(ui.cancelled, [123]);
  assert.equal(ui.context.scanStream, null);
  assert.equal(ui.context.scanFrameHandle, null);
  assert.equal(ui.video.srcObject, null);
  assert.equal(ui.context.scanDetector, null);
  assert.equal(ui.context.scanBusy, false);
});
