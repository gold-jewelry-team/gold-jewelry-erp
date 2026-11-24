import assert from "node:assert/strict";
import fs from "node:fs";
import test from "node:test";

const html = fs.readFileSync("app/static/index.html", "utf8");
const router = fs.readFileSync("app/routers/expenses.py", "utf8");

test("unpaid expense rows support edit and void while paid and void rows remain immutable", () => {
  assert.match(html, /data-edit-expense=/);
  assert.match(html, /data-void-expense=/);
  assert.match(html, /row\.status==="UNPAID"/);
  assert.match(html, /editingExpenseId/);
  assert.match(router, /@router\.patch\("\/\{expense_id\}"/);
  assert.match(router, /@router\.post\("\/\{expense_id\}\/void"/);
  assert.match(router, /只有未付款費用可以修改/);
  assert.match(router, /只有未付款費用可以作廢/);
});

test("expense edit mode does not allow changing payment method", () => {
  assert.ok(html.includes('$("expensePaymentMethod").disabled=true'));
  assert.match(html, /expenseCancelEdit/);
  assert.match(html, /resetExpenseEditor/);
});
