import assert from "node:assert/strict";
import test from "node:test";

import {
  buildExpenseAnalyticsHref,
  buildMerchantsByNameHref,
  buildTransfersSpaceHref,
  canCreateSavingsGoalFromReport,
} from "./contextual-navigation";

test("links a saved expense to the current-month Expenses analytics tab", () => {
  assert.equal(
    buildExpenseAnalyticsHref("Ristoranti"),
    "/analytics?tab=expenses&months=1&category=Ristoranti",
  );
});

test("opens the Voci lens with the raw names, without automatic grouping", () => {
  const href = buildMerchantsByNameHref();
  const params = new URLSearchParams(href.split("?")[1]);
  assert.equal(href.split("?")[0], "/analytics");
  assert.equal(params.get("tab"), "expenses");
  assert.equal(params.get("dimension"), "merchants");
  assert.equal(params.get("group"), "0");
});

test("links a saved transfer to the Transfers tab in My Space", () => {
  assert.equal(buildTransfersSpaceHref(), "/spazio?tab=transfers");
});

test("shows the savings-goal CTA only for a monthly report with positive net savings", () => {
  assert.equal(
    canCreateSavingsGoalFromReport({
      report_type: "monthly",
      report_data: { monthly_history: [{ net: 120 }] },
    }),
    true,
  );
  assert.equal(
    canCreateSavingsGoalFromReport({
      report_type: "monthly",
      report_data: { monthly_history: [{ net: 0 }] },
    }),
    false,
  );
  assert.equal(
    canCreateSavingsGoalFromReport({ report_type: "weekly", report_data: {} }),
    false,
  );
});
