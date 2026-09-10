import assert from "node:assert/strict";
import test from "node:test";

import {
  buildMonthlyBudgetGuidance,
  validateGeneralMonthlyBudget,
} from "./budgetViewModels";

test("suggests the sum of category budgets as minimum general monthly budget", () => {
  assert.deepEqual(buildMonthlyBudgetGuidance([
    { monthly_budget: 300 },
    { monthly_budget: null },
    { monthly_budget: 150.5 },
  ]), {
    categoryBudgetTotal: 450.5,
    suggestedBudget: 450.5,
    hasCategoryBudgets: true,
  });
});

test("normalizes numeric category budgets returned as strings", () => {
  assert.deepEqual(buildMonthlyBudgetGuidance([
    { monthly_budget: "300.00" },
    { monthly_budget: "150.50" },
  ]), {
    categoryBudgetTotal: 450.5,
    suggestedBudget: 450.5,
    hasCategoryBudgets: true,
  });
});

test("allows a general monthly budget equal to the category budget total", () => {
  assert.deepEqual(validateGeneralMonthlyBudget("450.50", 450.5), { ok: true, value: 450.5 });
});

test("rejects a general monthly budget lower than the category budget total", () => {
  assert.deepEqual(validateGeneralMonthlyBudget("400", 450.5), {
    ok: false,
    error: "Il budget mensile generale non puo' essere minore della somma dei budget categoria.",
  });
});

test("allows a positive general monthly budget when there are no category budgets", () => {
  assert.deepEqual(validateGeneralMonthlyBudget("250", 0), { ok: true, value: 250 });
});
