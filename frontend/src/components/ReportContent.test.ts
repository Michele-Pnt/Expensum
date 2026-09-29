import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

import {
  buildMonthlyBarData,
  formatBudgetSpendReadout,
} from "./reportChartData";

function cssSource(): string {
  return readFileSync(new URL("../app/reports/reports.module.css", import.meta.url), "utf8");
}

test("keeps full category identity when axis labels collide", () => {
  const rows = buildMonthlyBarData({
    spent_by_cat: { "Spesa alimentare": 30, "Spesa alimentari": 80 },
    budget_by_cat: { "Spesa alimentare": 300, "Spesa alimentari": 90 },
  }).rows;

  assert.notEqual(rows[0].id, rows[1].id);
  assert.deepEqual(formatBudgetSpendReadout(rows.find((row) => row.id === "Spesa alimentare")!), [
    "Budget: €300.00",
    "Speso: €30.00",
  ]);
});

test("renders stacked table records on phone widths", () => {
  const css = cssSource();
  assert.match(css, /@media \(max-width: 640px\)[\s\S]*\.dataTable td::before/);
  assert.match(css, /@media \(max-width: 640px\)[\s\S]*\.tableWrap\s*\{\s*overflow:\s*hidden/);
  assert.match(css, /\.dataTable tbody tr\s*\{[\s\S]*width:\s*calc\(100% - 1\.3rem\)/);
});

test("keeps the desktop table scrolling behavior outside the phone breakpoint", () => {
  const tableWrap = cssSource().match(/\.tableWrap\s*\{[^}]*\}/)?.[0] ?? "";
  assert.match(tableWrap, /overflow-x:\s*auto/);
});

test("keeps report chrome inside a 320px viewport", () => {
  const css = cssSource();
  const generateRow = css.match(/\.generateRow\s*\{[^}]*\}/)?.[0] ?? "";
  const reportCard = css.match(/\.reportCard\s*\{[^}]*\}/)?.[0] ?? "";
  const reportCardLeft = css.match(/\.reportCardLeft\s*\{[^}]*\}/)?.[0] ?? "";
  const kpiValue = css.match(/\.kpiValue\s*\{[^}]*\}/)?.[0] ?? "";
  const lockedOverlay = css.match(/\.lockedOverlay\s*\{[^}]*\}/)?.[0] ?? "";

  assert.match(generateRow, /flex-wrap:\s*wrap/);
  assert.match(reportCard, /min-width:\s*0/);
  assert.match(reportCard, /box-sizing:\s*border-box/);
  assert.match(reportCardLeft, /min-width:\s*0/);
  assert.match(kpiValue, /overflow-wrap:\s*anywhere/);
  assert.match(lockedOverlay, /box-sizing:\s*border-box/);
});
