import assert from "node:assert/strict";
import fs from "node:fs";
import test from "node:test";
import vm from "node:vm";

const html = fs.readFileSync("app/static/index.html", "utf8");
const legacyPricingCases = JSON.parse(fs.readFileSync("tests/fixtures/legacy_pricing_cases.json", "utf8"));

function extract(startMarker, endMarker) {
  const start = html.indexOf(startMarker);
  assert.notEqual(start, -1, `Missing function marker: ${startMarker}`);
  const end = html.indexOf(endMarker, start);
  assert.notEqual(end, -1, `Missing end marker: ${endMarker}`);
  return html.slice(start, end).trim();
}

function makeElement(value = "") {
  return {
    value,
    checked: false,
    textContent: "",
    innerHTML: "",
    focused: false,
    classList: {
      toggle() {},
      add() {},
      remove() {},
    },
    focus() { this.focused = true; },
  };
}

function setup(values = {}) {
  const elements = new Map();
  const get = (id) => {
    if (!elements.has(id)) elements.set(id, makeElement(values[id] ?? ""));
    return elements.get(id);
  };
  const context = {
    $: get,
    inventoryProducts: [],
    quoteSelectedProducts: [],
    quoteStockRowsByProduct: new Map(),
    currentGoldPriceRows: {
      SELL: { currency_code: "TWD", price_value: 15000, unit_code: "QIAN" },
      BUY: { currency_code: "TWD", price_value: 14000, unit_code: "QIAN" },
    },
    companyId: "company-1",
    selectedSiteId: "site-1",
    quoteCurrentTotal: null,
    quoteRoundTwd: (value) => Math.round(Number(value)),
    quoteMoney: (value) => Number(value).toLocaleString("en-US", { maximumFractionDigits: 2 }),
    convertGoldPrice: (value, fromUnit, toUnit) => fromUnit === toUnit ? Number(value) : null,
    goldUnitLabel: () => "錢",
    escapeHtml: (value) => String(value),
    quoteSetStatus(message, isError = false) {
      get("quoteStatus").textContent = message;
      get("quoteStatus").isError = isError;
    },
    renderQuoteLines() {},
    updateQuoteTradeInRatioVisibility() {},
    async loadQuoteStockBalances() {},
  };
  context.quoteTradeInInput = undefined;
  vm.createContext(context);
  vm.runInContext(extract("function quoteTradeInInput(){", "\nfunction renderQuoteEntryPreview(){"), context);
  vm.runInContext(extract("function quoteCalculateLineAmount(", "\nfunction renderQuoteEntryPreview(){"), context);
  vm.runInContext(extract("function renderQuoteEntryPreview(){", "\nasync function addQuoteProduct(){"), context);
  vm.runInContext(extract("async function addQuoteProduct(){", "\nasync function createCustomerOrderFromQuote(){"), context);
  return { context, get };
}

test("臨時估價不選商品、不填名稱，只輸入重量與工錢即可試算", () => {
  const { context, get } = setup({
    quoteProduct: "",
    quoteManualName: "",
    quoteWeight: "1.2",
    quoteWeightUnit: "QIAN",
    quoteLaborFee: "500",
    quotePaymentMethod: "CASH",
  });

  context.renderQuoteEntryPreview();

  const preview = get("quoteEntryPreview").innerHTML;
  assert.match(preview, /臨時估價即時試算/);
  assert.match(preview, /預估應收：NT\$ 18,500/);
});

test("外店舊金 1.429 錢按 95% 折抵後無條件捨去為 1.35 錢", () => {
  const { context, get } = setup({
    quoteProduct: "",
    quoteManualName: "",
    quoteWeight: "2",
    quoteWeightUnit: "QIAN",
    quoteLaborFee: "500",
    quotePaymentMethod: "CASH",
    quoteHasTradeIn: "",
    quoteOldGoldWeight: "1.429",
    quoteTradeInSource: "EXTERNAL",
    quoteTradeInRatio: "95",
  });
  get("quoteHasTradeIn").checked = true;

  context.renderQuoteEntryPreview();

  const preview = get("quoteEntryPreview").innerHTML;
  assert.match(preview, /折算 1\.35 錢/);
  assert.match(preview, /預估應收：NT\$ 10,250/);
});

test("本店舊金超過新商品重量時顯示店家找補，不套用刷卡費", () => {
  const { context, get } = setup({
    quoteProduct: "",
    quoteManualName: "",
    quoteWeight: "1",
    quoteWeightUnit: "QIAN",
    quoteLaborFee: "300",
    quotePaymentMethod: "CARD",
    quoteOldGoldWeight: "1.5",
    quoteTradeInSource: "LOCAL",
    quoteTradeInRatio: "95",
  });
  get("quoteHasTradeIn").checked = true;

  context.renderQuoteEntryPreview();

  const preview = get("quoteEntryPreview").innerHTML;
  assert.match(preview, /本店應付客人：NT\$ 6,700/);
  assert.doesNotMatch(preview, /刷卡 5% 手續費/);
});

test("不選商品、不填名稱仍可加入報價清單，並以臨時估價作為名稱", async () => {
  const { context, get } = setup({
    quoteProduct: "",
    quoteManualName: "",
    quoteManualSize: "",
    quoteWeight: "1.2",
    quoteWeightUnit: "QIAN",
    quoteLaborFee: "500",
    quoteOldGoldWeight: "0",
    quoteTradeInSource: "",
    quoteTradeInRatio: "95",
    quoteProductSearch: "",
    quoteProductCode: "",
  });

  await context.addQuoteProduct();

  assert.equal(context.quoteSelectedProducts.length, 1);
  const line = context.quoteSelectedProducts[0];
  assert.equal(line.isEstimate, true);
  assert.equal(line.product.name, "臨時估價");
  assert.equal(line.product.product_code, "臨時估價");
  assert.equal(line.weight, "1.2");
  assert.equal(line.labor, "500");
  assert.equal(get("quoteStatus").isError, false);
  assert.match(get("quoteStatus").textContent, /臨時估價已加入報價清單/);
});

test("缺少重量時阻止加入並聚焦重量欄位", async () => {
  const { context, get } = setup({
    quoteProduct: "",
    quoteManualName: "",
    quoteWeight: "",
    quoteWeightUnit: "QIAN",
    quoteLaborFee: "500",
  });

  await context.addQuoteProduct();

  assert.equal(context.quoteSelectedProducts.length, 0);
  assert.equal(get("quoteWeight").focused, true);
  assert.match(get("quoteStatus").textContent, /重量必須大於 0/);
});

test("共用計價函式符合舊版四種舊金換新金公式", () => {
  const { context } = setup();
  const calculate = context.quoteCalculateLineAmount;

  const noTradeIn = calculate({
    newWeight: 2, sellRate: 12000, buyRate: 11000, laborFee: 800,
  });
  assert.equal(noTradeIn.amount, 24800);

  const localLess = calculate({
    newWeight: 2, sellRate: 12000, buyRate: 11000, laborFee: 800,
    oldWeight: 1.25, tradeInSource: "LOCAL",
  });
  assert.equal(localLess.adjustedOldWeight, 1.25);
  assert.equal(localLess.amount, 9800);

  const externalLess = calculate({
    newWeight: 2, sellRate: 12000, buyRate: 11000, laborFee: 800,
    oldWeight: 1.333, tradeInSource: "EXTERNAL", tradeInRatio: 0.95,
  });
  assert.equal(externalLess.adjustedOldWeight, 1.26);
  assert.equal(externalLess.amount, 9680);

  const externalExcess = calculate({
    newWeight: 1, sellRate: 12000, buyRate: 11000, laborFee: 500,
    oldWeight: 2, tradeInSource: "EXTERNAL", tradeInRatio: 0.95,
  });
  assert.equal(externalExcess.adjustedOldWeight, 1.9);
  assert.equal(context.quoteRoundTwd(externalExcess.amount), -9400);
});

test("報價輸入預覽與報價清單都呼叫同一個計價函式", () => {
  const cartCalculation = extract("function renderQuoteCalculation(){", "\nfunction quoteTradeInInput(){");
  const entryPreview = extract("function renderQuoteEntryPreview(){", "\nasync function addQuoteProduct(){");
  assert.match(cartCalculation, /quoteCalculateLineAmount\(/);
  assert.match(entryPreview, /quoteCalculateLineAmount\(/);
});

test("混合付款時單件輸入預覽不會把未計算刷卡費的金額誤標為最終應收", () => {
  const { context, get } = setup({
    quoteProduct: "",
    quoteManualName: "",
    quoteWeight: "1.2",
    quoteWeightUnit: "QIAN",
    quoteLaborFee: "500",
    quotePaymentMethod: "MIXED",
  });

  context.renderQuoteEntryPreview();

  const preview = get("quoteEntryPreview").innerHTML;
  assert.match(preview, /商品金額（未含刷卡手續費）：NT\$ 18,500/);
  assert.match(preview, /加入報價清單並配平刷卡／現金金額後，會依刷卡部分加收 5%/);
  assert.doesNotMatch(preview, /預估應收：NT\$ 18,500/);
});


test("browser quote pricing matches the shared legacy golden cases", () => {
  const { context } = setup();

  for (const item of legacyPricingCases) {
    const result = context.quoteCalculateLineAmount({
      newWeight: Number(item.new_weight),
      sellRate: Number(item.sell_gold_price),
      buyRate: Number(item.buy_gold_price),
      laborFee: Number(item.labor_fee),
      oldWeight: Number(item.old_weight),
      tradeInSource: item.trade_in_source,
      tradeInRatio: Number(item.trade_in_ratio),
    });

    assert.equal(result.adjustedOldWeight, Number(item.adjusted_old_weight), item.name);
    assert.equal(result.amount, Number(item.subtotal), item.name);
    assert.equal(context.quoteRoundTwd(result.amount), Number(item.final_amount), item.name);
  }
});
