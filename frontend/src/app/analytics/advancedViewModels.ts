/** Granularità supportate dagli endpoint analytics avanzati. */
export type AggregationGranularity = "monthly" | "quarterly" | "yearly";

/** Metadata di un bucket nel formato usato dai view model frontend. */
export type AnalyticsBucket = {
  periodKey: string;
  periodLabel: string;
  isPartial: boolean;
  monthsIncluded: number;
};

/** Riga categoria restituita dagli endpoint avanzati (DTO snake_case). */
export type CategoryRow = {
  name: string;
  amount: number;
  period_key?: string;
  period_label?: string;
  is_partial?: boolean;
  months_included?: number;
  month?: string;
};

export type HistoricCategory = {
  name: string;
  total: number;
  monthlyAverage: number;
};

export type CategoryTrendPoint = AnalyticsBucket & { amount: number };
export type CategoryTrendSeries = { name: string; points: CategoryTrendPoint[] };
export type CategoryTrendFocus = {
  focus: CategoryTrendSeries;
  supporting: CategoryTrendSeries[];
};

/** DTO del confronto mensile restituito dal backend. */
export type MonthComparisonEntry = {
  category: string;
  current_month: number;
  last_month: number;
  avg_3m: number;
  change_pct: number;
};

export type DumbbellRow = {
  name: string;
  current: number;
  previous: number;
  average: number;
  changePercentage: number;
};

export type IncomeTransaction = {
  id?: number;
  name?: string;
  income_type?: string | null;
  income_category?: string | { name?: string | null } | null;
  amount: number;
  date: string;
  account?: string;
};

export type IncomeCategorySummary = { name: string; total: number; count: number; months_active: number; recurring: boolean };
export type IncomeNatureSummary = { name: "Ricorrenti" | "Straordinarie"; total: number; count: number };

/** Aggrega le entrate per categoria e distingue le categorie ricorrenti dalle altre. */
export function buildIncomeBreakdown(rows: IncomeTransaction[]): {
  byCategory: IncomeCategorySummary[];
  byNature: IncomeNatureSummary[];
} {
  const categories = new Map<string, { total: number; count: number; months: Set<string>; dates: string[] }>();
  for (const row of rows) {
    const category = typeof row.income_category === "string"
      ? row.income_category
      : row.income_category?.name;
    const name = (category || row.income_type || "Altra entrata").trim() || "Altra entrata";
    const current = categories.get(name) ?? { total: 0, count: 0, months: new Set<string>(), dates: [] };
    current.total += Number(row.amount) || 0;
    current.count += 1;
    current.months.add(String(row.date).slice(0, 7));
    current.dates.push(String(row.date).slice(0, 10));
    categories.set(name, current);
  }
  const byCategory = [...categories.entries()]
    .map(([name, value]) => {
      const dates = [...new Set(value.dates)].sort();
      const days = dates.map((date) => Number(date.slice(8, 10)));
      const monthKeys = [...new Set(dates.map((date) => date.slice(0, 7)))].sort();
      const consecutive = monthKeys.every((month, index) => {
        if (index === 0) return true;
        const previous = monthKeys[index - 1].split("-").map(Number);
        const current = month.split("-").map(Number);
        return current[0] * 12 + current[1] - (previous[0] * 12 + previous[1]) === 1;
      });
      const stableDay = days.length >= 2 && Math.max(...days) - Math.min(...days) <= 5;
      return { name, total: Math.round(value.total * 100) / 100, count: value.count, months_active: value.months.size, recurring: monthKeys.length >= 2 && consecutive && stableDay };
    })
    .sort((a, b) => b.total - a.total || a.name.localeCompare(b.name));
  const byNature: IncomeNatureSummary[] = (["Ricorrenti", "Straordinarie"] as const).map((name) => {
    const recurring = name === "Ricorrenti";
    const selected = byCategory.filter((category) => category.recurring === recurring);
    return { name, total: Math.round(selected.reduce((sum, category) => sum + category.total, 0) * 100) / 100, count: selected.reduce((sum, category) => sum + category.count, 0) };
  });
  return { byCategory, byNature };
}

function bucketFromRow(row: CategoryRow): AnalyticsBucket {
  const periodKey = row.period_key ?? row.period_label ?? row.month ?? "";
  const periodLabel = row.period_label ?? row.month ?? periodKey;
  return {
    periodKey,
    periodLabel,
    isPartial: row.is_partial ?? false,
    monthsIncluded: row.months_included ?? 1,
  };
}

function roundAmount(value: number): number {
  return Math.round((value + Number.EPSILON) * 100) / 100;
}

/** Aggrega l'intero intervallo e restituisce le cinque categorie più rilevanti. */
export function buildTopCategoryHistory(rows: CategoryRow[]): HistoricCategory[] {
  const totals = new Map<string, { total: number; months: number; buckets: Set<string> }>();
  for (const row of rows) {
    const current = totals.get(row.name) ?? { total: 0, months: 0, buckets: new Set<string>() };
    current.total += row.amount;
    const bucket = bucketFromRow(row);
    if (row.amount > 0 && !current.buckets.has(bucket.periodKey)) {
      current.months += bucket.monthsIncluded;
      current.buckets.add(bucket.periodKey);
    }
    totals.set(row.name, current);
  }

  return [...totals.entries()]
    .map(([name, value]) => ({
      name,
      total: roundAmount(value.total),
      monthlyAverage: roundAmount(value.total / Math.max(value.months, 1)),
    }))
    .sort((left, right) => right.total - left.total || left.name.localeCompare(right.name))
    .slice(0, 5);
}

/** Prepara una serie principale e al massimo quattro mini-serie di supporto. */
export function buildCategoryTrendFocus(
  rows: CategoryRow[],
  focusName?: string,
): CategoryTrendFocus {
  const history = buildTopCategoryHistory(rows);
  const selectedName = focusName && rows.some((row) => row.name === focusName)
    ? focusName
    : history[0]?.name ?? focusName ?? "";
  const totals = new Map<string, number>();
  for (const row of rows) totals.set(row.name, (totals.get(row.name) ?? 0) + row.amount);
  const names = [...totals.entries()]
    .sort((left, right) => right[1] - left[1] || left[0].localeCompare(right[0]))
    .map(([name]) => name)
    .filter((name) => name !== "");

  const series = new Map<string, Map<string, CategoryTrendPoint>>();
  for (const row of rows) {
    const bucket = bucketFromRow(row);
    const category = series.get(row.name) ?? new Map<string, CategoryTrendPoint>();
    const previous = category.get(bucket.periodKey);
    category.set(bucket.periodKey, {
      ...bucket,
      amount: roundAmount((previous?.amount ?? 0) + row.amount),
    });
    series.set(row.name, category);
  }

  const makeSeries = (name: string): CategoryTrendSeries => ({
    name,
    points: [...(series.get(name)?.values() ?? [])].sort((left, right) =>
      left.periodKey.localeCompare(right.periodKey)),
  });

  return {
    focus: makeSeries(selectedName),
    supporting: names.filter((name) => name !== selectedName).map(makeSeries),
  };
}

/** Mappa il DTO del confronto nel formato compatto per il grafico dumbbell. */
export function buildCategoryComparison(rows: MonthComparisonEntry[]): DumbbellRow[] {
  return rows
    .map((row): DumbbellRow => ({
      name: row.category,
      current: row.current_month,
      previous: row.last_month,
      average: row.avg_3m,
      changePercentage: row.change_pct,
    }))
    .sort((left, right) => right.changePercentage - left.changePercentage);
}

/** Rende esplicito quando il bucket annuale corrente è ancora incompleto. */
export function readoutForPeriod(
  bucket: Pick<AnalyticsBucket, "periodLabel" | "isPartial"> & Partial<Pick<AnalyticsBucket, "periodKey">>,
): string {
  const isPartialYear = bucket.isPartial && /^\d{4}$/.test(bucket.periodKey ?? bucket.periodLabel);
  return isPartialYear ? `${bucket.periodLabel} · anno in corso` : bucket.periodLabel;
}
