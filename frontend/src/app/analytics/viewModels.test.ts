import assert from "node:assert/strict";
import test from "node:test";

import {
  buildCategoryDetail,
  buildMergeCandidates,
  buildExplorerRows,
  buildMonthEndProjection,
  buildMonthlySpendingTrend,
  buildSpendingChanges,
  buildTodaySummary,
  periodToMonths,
} from "./viewModels";

test("projects month-end balance from the expenses recorded so far", () => {
  assert.deepEqual(buildMonthEndProjection({
    savings: [{ month: "ago 26", income: 2_000, expenses: 1_000, net: 1_000 }],
    now: new Date(2026, 7, 16),
  }), { currentAmount: 1_000, projectedAdditionalExpenses: 937.5, projectedEndAmount: 62.5 });
});

test("returns null when there are no savings entries for the projection", () => {
  assert.equal(buildMonthEndProjection({ savings: [], now: new Date(2026, 7, 16) }), null);
});

test("projects no additional expenses on the final day of the month", () => {
  assert.deepEqual(buildMonthEndProjection({
    savings: [{ month: "ago 26", income: 2_000, expenses: 1_000, net: 1_000 }],
    now: new Date(2026, 7, 31),
  }), { currentAmount: 1_000, projectedAdditionalExpenses: 0, projectedEndAmount: 1_000 });
});

test("uses the second ordered month as current for month-over-month increases", () => {
  assert.deepEqual(buildSpendingChanges([
    { month: "lug 26", name: "Bollette", amount: 100 },
    { month: "ago 26", name: "Bollette", amount: 180 },
  ]), [{ label: "Bollette", amount: 180, increase: 80 }]);
});

test("calculates the percentage increase in total spending from the previous month", () => {
  assert.deepEqual(buildMonthlySpendingTrend({
    currentTotal: 850,
    entries: [
      { month: "ago 26", name: "Casa", amount: 500 },
      { month: "ago 26", name: "Spesa", amount: 180 },
      { month: "set 26", name: "Casa", amount: 600 },
      { month: "set 26", name: "Spesa", amount: 250 },
    ],
  }), { direction: "up", percentage: 25, previousTotal: 680 });
});

test("calculates the percentage decrease in total spending from the previous month", () => {
  assert.deepEqual(buildMonthlySpendingTrend({
    currentTotal: 500,
    entries: [
      { month: "ago 26", name: "Casa", amount: 800 },
      { month: "set 26", name: "Casa", amount: 500 },
    ],
  }), { direction: "down", percentage: 38, previousTotal: 800 });
});

test("hides the spending trend when there is no comparable previous month", () => {
  assert.equal(buildMonthlySpendingTrend({
    currentTotal: 850,
    entries: [{ month: "set 26", name: "Casa", amount: 850 }],
  }), null);
});

test("shows a full decrease when this month has no expenses yet", () => {
  assert.deepEqual(buildMonthlySpendingTrend({
    currentTotal: 0,
    entries: [{ month: "ago 26", name: "Casa", amount: 800 }],
  }), { direction: "down", percentage: 100, previousTotal: 800 });
});

test("treats a category present only in the current month as a full increase", () => {
  assert.deepEqual(buildSpendingChanges([
    { month: "lug 26", name: "Casa", amount: 100 },
    { month: "ago 26", name: "Ristoranti", amount: 180 },
  ]), [{ label: "Ristoranti", amount: 180, increase: 180 }]);
});

test("excludes a category present only in the previous month", () => {
  const changes = buildSpendingChanges([
    { month: "lug 26", name: "Bollette", amount: 100 },
    { month: "ago 26", name: "Ristoranti", amount: 180 },
  ]);

  assert.deepEqual(changes, [{ label: "Ristoranti", amount: 180, increase: 180 }]);
  assert.equal(changes.some((change) => change.label === "Bollette"), false);
});

test("maps semantic periods to the existing API month limits", () => {
  assert.equal(periodToMonths("current"), 1);
  assert.equal(periodToMonths("three_months"), 3);
  assert.equal(periodToMonths("year"), 12);
  assert.equal(periodToMonths("custom", 5), 5);
});

test("makes the highest budget percentage the first attention row", () => {
  const summary = buildTodaySummary({
    savings: [{ month: "ago 26", income: 2_000, expenses: 1_258, net: 742 }],
    budgetStatus: [{
      category: "Ristoranti",
      budget: 315,
      spent: 281,
      remaining: 34,
      percentage: 89,
    }],
  });

  assert.deepEqual(summary.attentions[0], {
    label: "Ristoranti",
    value: "89% del budget",
    tone: "warning",
  });
});

test("uses the general monthly budget to calculate the remaining spending margin", () => {
  const summary = buildTodaySummary({
    savings: [{ month: "ago 26", income: 2_000, expenses: 1_258, net: 742 }],
    budgetStatus: [],
    monthlyBudget: 1_500,
    totalSpent: 1_258,
  });

  assert.equal(summary.availableAmount, 242);
  assert.equal(summary.totalSpent, 1_258);
  assert.match(summary.statusLabel, /^Ti restano 242,00\s€ sul budget mensile generale$/u);
  assert.deepEqual(summary.attentions, []);
});

test("describes the remaining margin as category budgets when no general budget exists", () => {
  const summary = buildTodaySummary({
    savings: [{ month: "ago 26", income: 2_000, expenses: 1_258, net: 742 }],
    budgetStatus: [
      { category: "Casa", budget: 600, spent: 450, remaining: 150, percentage: 75 },
      { category: "Spesa", budget: 300, spent: 280, remaining: 20, percentage: 93 },
    ],
    monthlyBudget: null,
    totalSpent: 1_258,
  });

  assert.equal(summary.availableAmount, 170);
  assert.match(summary.statusLabel, /^Ti restano 170,00\s€ sui budget per categoria$/u);
});

test("preserves category overspending in the category-budget fallback", () => {
  assert.equal(buildTodaySummary({
    savings: [{ month: "ago 26", income: 2_000, expenses: 200, net: 1_800 }],
    budgetStatus: [
      { category: "Casa", budget: 100, spent: 200, remaining: 0, percentage: 200 },
      { category: "Spesa", budget: 100, spent: 0, remaining: 100, percentage: 0 },
    ],
    monthlyBudget: null,
    totalSpent: 200,
  }).availableAmount, 0);
});

test("returns a data-needed message when there are no savings entries", () => {
  assert.deepEqual(buildTodaySummary({ savings: [], budgetStatus: [] }), {
    availableAmount: null,
    totalSpent: 0,
    budgetTone: "neutral",
    statusLabel: "Imposta un budget mensile o dei budget per categoria per vedere il margine.",
    attentions: [],
  });
});

test("orders explorer categories by current-period amount and includes their share", () => {
  const rows = buildExplorerRows({
    dimension: "categories",
    totalAmount: 1_000,
    categories: [
      { name: "Ristoranti", amount: 281, count: 4 },
      { name: "Casa", amount: 510, count: 2 },
    ],
  });

  assert.deepEqual(rows[0], {
    label: "Casa",
    amount: 510,
    secondaryLabel: "2 operazioni",
    incidenceLabel: "Incide per il 51% sul totale speso nel periodo selezionato",
    percentage: 51,
  });
});

test("avoids a misleading percentage when the explorer total is zero", () => {
  assert.deepEqual(buildExplorerRows({
    dimension: "categories",
    totalAmount: 0,
    categories: [{ name: "Ristoranti", amount: 0, count: 1 }],
  }), [{
    label: "Ristoranti",
    amount: 0,
    secondaryLabel: "1 operazione",
    incidenceLabel: "Nessuna incidenza disponibile",
    percentage: undefined,
  }]);
});

test("suggests the historical average when a category has no budget", () => {
  assert.deepEqual(buildCategoryDetail({ category: "Ristoranti", average: 238 }), {
    category: "Ristoranti",
    budgetPrompt: { suggestedAmount: 238 },
  });
});

test("does not show a budget prompt when a positive budget already exists", () => {
  assert.deepEqual(buildCategoryDetail({ category: "Casa", average: 238, budget: 300 }), {
    category: "Casa",
    budgetPrompt: null,
  });
});

test("offers only same-category groups as merge candidates, richest first", () => {
  const clusters = [
    { id: 1, anchor_text: "Ape", category_id: 3, category: "Svago", total: 40, count: 4, variants: [] },
    { id: 2, anchor_text: "Aperitivo", category_id: 3, category: "Svago", total: 90, count: 6, variants: [] },
    { id: 3, anchor_text: "Ape 50", category_id: 7, category: "Auto", total: 500, count: 2, variants: [] },
    { id: 4, anchor_text: "Spritz", category_id: 3, category: "Svago", total: 60, count: 5, variants: [] },
  ];

  assert.deepEqual(
    buildMergeCandidates(clusters, 1, 3).map((cluster) => cluster.id),
    [2, 4],
  );
});

test("returns no merge candidates when the group has no category", () => {
  const clusters = [
    { id: 1, anchor_text: "Ape", category_id: null, category: "Altro", total: 40, count: 4, variants: [] },
    { id: 2, anchor_text: "Aperitivo", category_id: 3, category: "Svago", total: 90, count: 6, variants: [] },
  ];

  assert.deepEqual(buildMergeCandidates(clusters, 1, null), []);
});
