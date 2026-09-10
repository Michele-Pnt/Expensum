import assert from "node:assert/strict";
import test from "node:test";

import {
  activeIncomeCategories,
  formatIncomeDate,
  incomeCategoryLabel,
} from "./incomeCategoryViewModels";

test("income category label prefers the resolved category over legacy type", () => {
  assert.equal(
    incomeCategoryLabel({ date: "2026-09-02", income_category: { name: "Freelance" }, income_type: "Stipendio" }),
    "Freelance",
  );
});

test("income category label falls back to legacy data and preserves day-first date", () => {
  assert.equal(incomeCategoryLabel({ date: "2026-09-02", income_type: "Rimborso" }), "Rimborso");
  assert.equal(formatIncomeDate("2026-09-02"), "02-09-2026");
});

test("the runtime catalogue keeps every persisted custom category", () => {
  assert.deepEqual(
    activeIncomeCategories([
      { id: 9, name: "Consulenza", monthly_budget: null, average: 0, archived: false },
      { id: 10, name: "Vecchia", monthly_budget: null, average: 0, archived: true },
    ]),
    [
      { id: 9, name: "Consulenza", monthly_budget: null, average: 0, archived: false },
      { id: 10, name: "Vecchia", monthly_budget: null, average: 0, archived: true },
    ],
  );
});
