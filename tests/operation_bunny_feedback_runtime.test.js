import assert from "node:assert/strict";
import fs from "node:fs";
import test from "node:test";
import vm from "node:vm";

const html = fs.readFileSync("app/static/index.html", "utf8");
const start = html.indexOf("function isBunnyPersistedOperationSuccess(");
const end = html.indexOf("\nconst message=", start);
assert.notEqual(start, -1, "Persisted-operation success helper must exist");
assert.notEqual(end, -1, "Operation feedback helpers must have a stable boundary");
const source = html.slice(start, end);
const context = {};
vm.createContext(context);
vm.runInContext(source, context);

test("saved and updated operations receive rabbit confirmation", () => {
  const examples = [
    "公司已建立。",
    "商品資料已更新。",
    "匯率已儲存於目前瀏覽器。",
    "客訂收款已成功登錄。",
    "採購單已送出。",
    "本次驗收成功，已新增庫存入庫流水。",
    "銷售已完成；正式商品已扣除庫存。",
    "庫存調整已成功入帳。",
  ];
  for (const message of examples) {
    assert.equal(context.isBunnyPersistedOperationSuccess(message, false), true, message);
  }
});

test("lookup and temporary progress messages do not masquerade as saved operations", () => {
  const examples = [
    "已找到商品：G00R-21663",
    "已產生編號：G00R-21664",
    "正在更新庫存資料…",
    "請先選擇公司。",
    "已產生編號：G00R-21664；此號碼已保留，未使用也不會回收。",
    "已確認商品：G00R-21663；請繼續掃描下一件。",
  ];
  for (const message of examples) {
    assert.equal(context.isBunnyPersistedOperationSuccess(message, false), false, message);
  }
});

test("partial success followed by a refresh failure is not shown as a completed operation", () => {
  const examples = [
    "商品已更新，但畫面重新載入失敗：NetworkError",
    "退貨已建立，但部分畫面重新載入失敗：NetworkError",
    "操作已成功，但清單刷新失敗：NetworkError",
  ];
  for (const message of examples) {
    assert.equal(context.isBunnyPersistedOperationSuccess(message, false), false, message);
  }
});

test("error and partial-failure messages suppress the success rabbit", () => {
  assert.equal(context.isBunnyPersistedOperationSuccess("供應商付款已成功登錄，但清單更新失敗。", true), false);
  assert.equal(context.isBunnyPersistedOperationSuccess("商品已新增。", true), false);
});

test("feedback copy reflects the operation domain without repeating exact transaction details", () => {
  assert.match(context.bunnyOperationFeedbackCopy("供應商付款已成功登錄。"), /帳務紀錄已更新/);
  assert.match(context.bunnyOperationFeedbackCopy("庫存調整已成功入帳。"), /庫存作業已完成/);
  assert.match(context.bunnyOperationFeedbackCopy("銷售已完成。"), /交易資料已更新/);
  assert.match(context.bunnyOperationFeedbackCopy("公司已建立。"), /資料已儲存/);
});
