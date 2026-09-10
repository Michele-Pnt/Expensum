import assert from "node:assert/strict";
import test from "node:test";

import {
  buildIncomeBreakdown,
  buildCategoryComparison,
  buildCategoryTrendFocus,
  buildTopCategoryHistory,
  readoutForPeriod,
  type CategoryRow,
} from "./advancedViewModels";

const rows: CategoryRow[] = [
  { name: "Casa", amount: 500, period_key: "2026-01", period_label: "gen 26", is_partial: false, months_included: 1 },
  { name: "Casa", amount: 400, period_key: "2026-02", period_label: "feb 26", is_partial: false, months_included: 1 },
  { name: "Casa", amount: 300, period_key: "2026-03", period_label: "mar 26", is_partial: true, months_included: 1 },
  { name: "Cibo", amount: 250, period_key: "2026-01", period_label: "gen 26", is_partial: false, months_included: 1 },
  { name: "Cibo", amount: 250, period_key: "2026-02", period_label: "feb 26", is_partial: false, months_included: 1 },
];

test("ranks the historic top five over the entire selected range and exposes a monthly average", () => {
  assert.deepEqual(buildTopCategoryHistory(rows), [
    { name: "Casa", total: 1200, monthlyAverage: 400 },
    { name: "Cibo", total: 500, monthlyAverage: 250 },
  ]);
});

test("limits the main category trend to one focus category and keeps the rest as mini series", () => {
  const result = buildCategoryTrendFocus(rows, "Casa");
  assert.equal(result.focus.name, "Casa");
  assert.equal(result.supporting.length, 1);
  assert.equal(result.focus.points[0]?.periodKey, "2026-01");
  assert.equal(result.focus.points[0]?.periodLabel, "gen 26");
});

test("defaults the trend focus to the highest total category", () => {
  assert.equal(buildCategoryTrendFocus(rows).focus.name, "Casa");
});

test("converts month comparison API fields to the dumbbell view model", () => {
  assert.deepEqual(buildCategoryComparison([{
    category: "Casa", current_month: 300, last_month: 200, avg_3m: 250, change_pct: 50,
  }]), [{
    name: "Casa", current: 300, previous: 200, average: 250, changePercentage: 50,
  }]);
});

test("labels an incomplete current year without implying a complete annual total", () => {
  assert.equal(readoutForPeriod({ periodLabel: "2026", isPartial: true }), "2026 · anno in corso");
});

test("uses the period label as-is for complete periods", () => {
  assert.equal(readoutForPeriod({ periodLabel: "2025", isPartial: false }), "2025");
});

test("divides quarterly and yearly category totals by included months", () => {
  assert.deepEqual(buildTopCategoryHistory([
    { name: "Casa", amount: 900, period_key: "2026-Q1", period_label: "Q1 2026", months_included: 3 },
    { name: "Casa", amount: 1200, period_key: "2025", period_label: "2025", months_included: 12 },
  ]), [{ name: "Casa", total: 2100, monthlyAverage: 140 }]);
});

test("groups income by structured category, then legacy type, never transaction name", () => {
  const breakdown = buildIncomeBreakdown([
    { name: "Cliente Alpha", income_category: { name: "Consulenza" }, income_type: "Stipendio", amount: 100, date: "2026-01-10" },
    { name: "Cliente Beta", income_category: "Consulenza", amount: 100, date: "2026-02-10" },
    { name: "Premio progetto", income_type: "Bonus lavorativo", amount: 50, date: "2026-02-15" },
    { name: "Non usare questo nome", amount: 25, date: "2026-02-20" },
  ]);

  assert.deepEqual(breakdown.byCategory, [
    { name: "Consulenza", total: 200, count: 2, months_active: 2, recurring: true },
    { name: "Bonus lavorativo", total: 50, count: 1, months_active: 1, recurring: false },
    { name: "Altra entrata", total: 25, count: 1, months_active: 1, recurring: false },
  ]);
  assert.equal("bySource" in breakdown, false);
  assert.deepEqual(breakdown.byNature, [
    { name: "Ricorrenti", total: 200, count: 2 },
    { name: "Straordinarie", total: 75, count: 2 },
  ]);
});
