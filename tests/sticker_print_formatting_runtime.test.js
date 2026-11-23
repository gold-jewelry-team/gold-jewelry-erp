import assert from "node:assert/strict";
import fs from "node:fs";
import test from "node:test";

const html = fs.readFileSync("app/static/index.html", "utf8");
const start = html.indexOf("function printProductQrLabel(");
const end = html.indexOf("\nasync function beginProductLabelPrint(", start);
assert.notEqual(start, -1, "Sticker print function must exist");
assert.notEqual(end, -1, "Sticker print function boundary must exist");
const source = html.slice(start, end);

test("sticker weight uses the localized Chinese unit label, not the raw unit code", () => {
  assert.match(source, /weight\.toFixed\(2\)\s*\+\s*" "\s*\+\s*goldUnitLabel\(product\.weight_unit_code\s*\|\|\s*"QIAN"\)/);
  assert.doesNotMatch(source, /weight\.toFixed\(2\)\s*\+\s*" "\s*\+\s*\(product\.weight_unit_code\s*\|\|\s*""\)/);
});

test("sticker sales labor is displayed at the same 20pt size and bold weight as the weight", () => {
  assert.match(source, /\.weight\{font-size:20pt;font-weight:800/);
  assert.match(source, /\.labor\{font-size:20pt;font-weight:800/);
});

test("sticker unit mapping supports qian, gram, and tael in Chinese", () => {
  assert.match(html, /const GOLD_UNIT_LABELS=\{QIAN:"錢",GRAM:"公克",TAEL:"兩"\}/);
});
