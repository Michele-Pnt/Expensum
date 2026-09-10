import assert from "node:assert/strict";
import test from "node:test";

import {
  buildMonthAvailability,
  buildRecentMovements,
  formatMonthLabel,
} from "./homeViewModels";

test("labels the current month in Italian, uppercase", () => {
  assert.equal(formatMonthLabel(new Date("2026-09-04T10:00:00Z")), "SETTEMBRE 2026");
  assert.equal(formatMonthLabel(new Date("2026-01-31T10:00:00Z")), "GENNAIO 2026");
});

test("uses the monthly budget when set, showing what is left", () => {
  const availability = buildMonthAvailability({ monthlyBudget: 2000, totalSpent: 715.4, categoryBudgets: [] });
  assert.equal(availability.budget, 2000);
  assert.equal(availability.spent, 715.4);
  assert.equal(availability.remaining, 1284.6);
  assert.equal(availability.progress, 0.3577);
});

test("falls back to the sum of category budgets when no monthly budget is set", () => {
  const availability = buildMonthAvailability({
    monthlyBudget: null,
    totalSpent: 150,
    categoryBudgets: [{ budget: 200, spent: 100 }, { budget: 300, spent: 50 }],
  });
  assert.equal(availability.budget, 500);
  assert.equal(availability.remaining, 350);
});

test("a category without a budget never eats the budget of the others", () => {
  // Stesso scenario di Analytics: "Casa" ha un budget e ne ha speso metà, "Uscite"
  // non ne ha e spende 300. Il residuo mostrato deve restare positivo, come là.
  const availability = buildMonthAvailability({
    monthlyBudget: null,
    totalSpent: 400,
    categoryBudgets: [{ budget: 200, spent: 100 }],
  });
  assert.equal(availability.budget, 200);
  assert.equal(availability.remaining, 100);
  assert.equal(availability.isOverBudget, false);
});

test("reports no budget at all instead of inventing one", () => {
  const availability = buildMonthAvailability({ monthlyBudget: null, totalSpent: 80, categoryBudgets: [] });
  assert.equal(availability.budget, null);
  assert.equal(availability.remaining, null);
  assert.equal(availability.progress, null);
  assert.equal(availability.spent, 80);
});

test("never lets the progress bar overflow when the budget is exceeded", () => {
  const availability = buildMonthAvailability({ monthlyBudget: 100, totalSpent: 250, categoryBudgets: [] });
  assert.equal(availability.progress, 1);
  assert.equal(availability.remaining, -150);
  assert.equal(availability.isOverBudget, true);
});

test("a zero budget is treated as no budget, not as a division by zero", () => {
  const availability = buildMonthAvailability({ monthlyBudget: 0, totalSpent: 10, categoryBudgets: [] });
  assert.equal(availability.budget, null);
  assert.equal(availability.progress, null);
});

test("a month with more refunds than expenses never draws a negative bar", () => {
  const availability = buildMonthAvailability({ monthlyBudget: 500, totalSpent: -40, categoryBudgets: [] });
  assert.equal(availability.progress, 0);
  assert.equal(availability.remaining, 540);
  assert.equal(availability.isOverBudget, false);
});

test("a negative or non-finite budget counts as no budget", () => {
  assert.equal(buildMonthAvailability({ monthlyBudget: -100, totalSpent: 10, categoryBudgets: [] }).budget, null);
  assert.equal(buildMonthAvailability({ monthlyBudget: NaN, totalSpent: 10, categoryBudgets: [] }).budget, null);
  assert.equal(
    buildMonthAvailability({ monthlyBudget: Infinity, totalSpent: 10, categoryBudgets: [] }).budget,
    null,
  );
});

test("asking for no movements returns none", () => {
  assert.deepEqual(
    buildRecentMovements({
      expenses: [{ id: 1, date: "2026-09-01", name: "A", amount: 1, category: "X" }],
      incomes: [],
      limit: 0,
    }),
    [],
  );
});

test("merges expenses and incomes into one list, most recent first", () => {
  const movements = buildRecentMovements({
    expenses: [
      { id: 1, date: "2026-09-01", name: "Esselunga", amount: 42.8, category: "Spesa" },
      { id: 2, date: "2026-09-03", name: "Trenitalia", amount: 18.9, category: "Trasporti" },
    ],
    incomes: [{ id: 7, date: "2026-09-02", name: "Stipendio", amount: 1850, income_category: "Entrate" }],
    limit: 3,
  });

  assert.deepEqual(movements.map((m) => m.name), ["Trenitalia", "Stipendio", "Esselunga"]);
  assert.deepEqual(movements.map((m) => m.direction), ["out", "in", "out"]);
  assert.equal(movements[1].label, "Entrate");
});

test("keeps only the requested number of movements", () => {
  const movements = buildRecentMovements({
    expenses: [
      { id: 1, date: "2026-09-01", name: "A", amount: 1, category: "X" },
      { id: 2, date: "2026-09-02", name: "B", amount: 2, category: "X" },
      { id: 3, date: "2026-09-03", name: "C", amount: 3, category: "X" },
    ],
    incomes: [],
    limit: 2,
  });
  assert.deepEqual(movements.map((m) => m.name), ["C", "B"]);
});

test("gives every movement a key unique across expenses and incomes", () => {
  const movements = buildRecentMovements({
    expenses: [{ id: 1, date: "2026-09-01", name: "Spesa", amount: 10, category: "X" }],
    incomes: [{ id: 1, date: "2026-09-02", name: "Entrata", amount: 20, income_type: "Stipendio" }],
    limit: 5,
  });
  assert.equal(new Set(movements.map((m) => m.key)).size, 2);
});

test("survives an empty month without throwing", () => {
  assert.deepEqual(buildRecentMovements({ expenses: [], incomes: [], limit: 5 }), []);
});
