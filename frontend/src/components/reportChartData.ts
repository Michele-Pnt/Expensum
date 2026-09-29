/** Dati puri per i grafici Budget/Speso, senza dipendenze di rendering. */
export interface BudgetSpendChartRow {
  /** Identificatore stabile: il nome categoria non viene mai troncato. */
  id: string;
  /** Nome completo, mostrato dal tooltip. */
  name: string;
  /** Etichetta compatta solo per l'asse X. */
  axisLabel: string;
  Budget: number;
  Speso: number;
}

export interface MonthlyBarData {
  rows: BudgetSpendChartRow[];
  hasSpent: boolean;
}

type UnknownRecord = Record<string, unknown>;

function asRecord(value: unknown): UnknownRecord {
  return value !== null && typeof value === "object" && !Array.isArray(value)
    ? value as UnknownRecord
    : {};
}

function shortAxisLabel(name: string): string {
  return name.length > 12 ? `${name.slice(0, 11)}.` : name;
}

/**
 * Mantiene il nome integrale nel dato del grafico e distingue le etichette
 * abbreviate che altrimenti colliderebbero sull'asse X.
 */
function withAxisLabels(rows: Omit<BudgetSpendChartRow, "axisLabel">[]): BudgetSpendChartRow[] {
  const shortened = rows.map((row) => shortAxisLabel(row.name));
  const totals = new Map<string, number>();
  shortened.forEach((label) => totals.set(label, (totals.get(label) ?? 0) + 1));
  const positions = new Map<string, number>();

  return rows.map((row, index) => {
    const label = shortened[index];
    const total = totals.get(label) ?? 0;
    const position = (positions.get(label) ?? 0) + 1;
    positions.set(label, position);
    return {
      ...row,
      axisLabel: total > 1 ? `${label} ${position}` : label,
    };
  });
}

/** Costruisce le categorie del report settimanale, ordinate per budget. */
export function buildWeeklyBarData(budgetResults: UnknownRecord): BudgetSpendChartRow[] {
  const rows = Object.entries(budgetResults)
    .map(([category, result]) => ({
      id: category,
      name: category,
      Budget: Math.round(Number(asRecord(result).budget_monthly ?? 0)),
      Speso: Math.round(Number(asRecord(result).spent_month ?? 0)),
    }))
    .sort((a, b) => b.Budget - a.Budget)
    .slice(0, 8);
  return withAxisLabels(rows);
}

/** Costruisce le categorie del report mensile, ordinate per budget. */
export function buildMonthlyBarData(data: UnknownRecord): MonthlyBarData {
  const spent = asRecord(data.spent_by_cat ?? data.by_category);
  const budgets = asRecord(data.budget_by_cat);
  const hasSpent = Object.values(spent).some((value) => Number(value) > 0);
  const categories = new Set([...Object.keys(hasSpent ? spent : {}), ...Object.keys(budgets)]);
  const rows = Array.from(categories)
    .map((category) => ({
      id: category,
      name: category,
      Speso: Math.round(Number(spent[category] ?? 0)),
      Budget: Math.round(Number(budgets[category] ?? 0)),
    }))
    .filter((row) => row.Speso > 0 || row.Budget > 0)
    .sort((a, b) => b.Budget - a.Budget)
    .slice(0, 8);
  return { rows: withAxisLabels(rows), hasSpent };
}

/** Restituisce le due cifre nel solo ordine ammesso dal tooltip del grafico. */
export function formatBudgetSpendReadout(row: Pick<BudgetSpendChartRow, "Budget" | "Speso">): string[] {
  return [
    `Budget: €${row.Budget.toFixed(2)}`,
    `Speso: €${row.Speso.toFixed(2)}`,
  ];
}
