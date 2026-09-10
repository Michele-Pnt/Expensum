/** Build the contextual analytics URL shown after saving an expense. */
export function buildExpenseAnalyticsHref(category: string | null | undefined): string {
  const params = new URLSearchParams({ tab: "expenses", months: "1" });
  if (category) params.set("category", category);
  return `/analytics?${params.toString()}`;
}

/** Build the URL that opens Analytics on the "Voci" (merchants/items) explorer lens. */
export function buildMerchantsAnalyticsHref(): string {
  return "/analytics?tab=expenses&months=1&dimension=merchants";
}

/**
 * Come sopra, ma con le voci mostrate "Per nome": nessun raggruppamento
 * automatico delle descrizioni simili (`group=0`).
 */
export function buildMerchantsByNameHref(): string {
  return "/analytics?tab=expenses&months=1&dimension=merchants&group=0";
}

/** Build the contextual Space URL shown after saving a transfer. */
export function buildTransfersSpaceHref(): string {
  return "/spazio?tab=transfers";
}

type ReportForSavingsGoal = {
  report_type: string;
  report_data?: { monthly_history?: Array<{ net?: number }> } | null;
};

/** Return whether a monthly report proves positive net savings in its latest month. */
export function canCreateSavingsGoalFromReport(report: ReportForSavingsGoal): boolean {
  if (report.report_type !== "monthly") return false;
  const history = report.report_data?.monthly_history;
  const latestMonth = history?.at(-1);
  return typeof latestMonth?.net === "number" && latestMonth.net > 0;
}
