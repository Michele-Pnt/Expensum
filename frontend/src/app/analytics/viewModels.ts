import type {
  AnalyticsPeriod,
  BudgetStatusEntry,
  ExpenseLabelCluster,
  MonthEndForecast,
  SavingsEntry,
} from "./types";

export type AttentionTone = "critical" | "warning" | "neutral";

export type AttentionRow = {
  label: string;
  value: string;
  tone: AttentionTone;
};

export type TodaySummaryInput = {
  savings: SavingsEntry[];
  budgetStatus: BudgetStatusEntry[];
  monthlyBudget?: number | string | null;
  totalSpent?: number;
  currentPeriodKey?: string;
};

export type TodaySummary = {
  availableAmount: number | null;
  totalSpent: number;
  totalIncome: number;
  monthlySavings: number;
  budgetTone: AttentionTone;
  statusLabel: string;
  attentions: AttentionRow[];
};

export type ExplorerRow = {
  label: string;
  amount: number;
  secondaryLabel: string;
  incidenceLabel?: string;
  percentage?: number;
};

export type ExplorerRowsInput = {
  dimension: "categories" | "merchants" | "accounts";
  totalAmount: number;
  categories: Array<{ name: string; amount: number; count: number }>;
};

export type ExplorerPage<T> = {
  items: T[];
  hasMore: boolean;
};

export type CategoryDetail = {
  category: string;
  budgetPrompt: { suggestedAmount: number } | null;
};

export type MonthEndProjection = {
  currentAmount: number;
  projectedEndAmount: number;
  remainingExpectedIncome: number;
};

export type MonthlySavingsComparison = {
  direction: "up" | "down" | "flat";
  currentAmount: number;
  previousAmount: number;
  delta: number;
};

export type SpendingChangeEntry = {
  month: string;
  name: string;
  amount: number;
};

export type SpendingChange = {
  label: string;
  amount: number;
  increase: number;
};

export type MonthlySpendingTrend = {
  direction: "up" | "down" | "flat";
  percentage: number;
  previousTotal: number;
};

/** Traduce le scelte temporali dell'interfaccia nei mesi usati dalle API correnti. */
export function periodToMonths(period: AnalyticsPeriod, customMonths = 3): number {
  if (period === "current") return 1;
  if (period === "three_months") return 3;
  if (period === "year") return 12;
  return customMonths;
}

/** Crea un riepilogo operativo, privilegiando le categorie più urgenti. */
export function buildTodaySummary(input: TodaySummaryInput): TodaySummary {
  const monthlyBudget = input.monthlyBudget == null ? null : Number(input.monthlyBudget);
  const hasMonthlyBudget = monthlyBudget != null && Number.isFinite(monthlyBudget) && monthlyBudget > 0;
  const hasCategoryBudgets = input.budgetStatus.some((entry) => entry.budget > 0);
  const totalSpent = input.totalSpent ?? input.budgetStatus.reduce(
    (total, entry) => total + (entry.budget > 0 ? entry.spent : 0),
    0,
  );
  const availableAmount = hasMonthlyBudget
    ? Number((monthlyBudget - totalSpent).toFixed(2))
    : hasCategoryBudgets
      ? Number(input.budgetStatus
        .reduce((total, entry) => total + entry.budget - entry.spent, 0)
        .toFixed(2))
      : null;
  const budgetSpent = hasMonthlyBudget
    ? totalSpent
    : input.budgetStatus.reduce(
      (total, entry) => total + (entry.budget > 0 ? entry.spent : 0),
      0,
    );
  const budgetTotal = hasMonthlyBudget
    ? monthlyBudget
    : input.budgetStatus.reduce(
      (total, entry) => total + (entry.budget > 0 ? entry.budget : 0),
      0,
    );
  const budgetPercentage = budgetTotal > 0 ? (budgetSpent / budgetTotal) * 100 : null;
  const budgetTone: AttentionTone = budgetPercentage == null || budgetPercentage < 75
    ? "neutral"
    : budgetPercentage < 100
      ? "warning"
      : "critical";
  const statusLabel = availableAmount === null
    ? "Imposta un budget mensile o dei budget per categoria per vedere il margine."
    : availableAmount >= 0
      ? hasMonthlyBudget
        ? `Ti restano ${formatEuro(availableAmount)} sul budget mensile generale`
        : `Ti restano ${formatEuro(availableAmount)} sui budget per categoria`
      : hasMonthlyBudget
        ? `Hai superato il budget mensile generale di ${formatEuro(Math.abs(availableAmount))}`
        : `Hai superato i budget per categoria di ${formatEuro(Math.abs(availableAmount))}`;

  const attentions = [...input.budgetStatus]
    .sort((left, right) => right.percentage - left.percentage)
    .slice(0, 5)
    .map((entry): AttentionRow => ({
      label: entry.category,
      value: `${Math.round(entry.percentage)}% del budget`,
      tone: entry.percentage >= 100 ? "critical" : entry.percentage >= 85 ? "warning" : "neutral",
    }));

  const currentSavings = input.savings.find(
    (entry) => entry.period_key === (input.currentPeriodKey ?? currentCalendarPeriodKey()),
  );
  const totalIncome = currentSavings?.income ?? 0;
  const monthlySavings = currentSavings?.net ?? totalIncome - totalSpent;

  return {
    availableAmount,
    totalSpent,
    totalIncome,
    monthlySavings,
    budgetTone,
    statusLabel,
    attentions,
  };
}

/** Restituisce la chiave del mese calendario locale, senza dipendere dall'ordine delle righe API. */
export function currentCalendarPeriodKey(now = new Date()): string {
  return `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, "0")}`;
}

function formatEuro(value: number): string {
  return value.toLocaleString("it-IT", { style: "currency", currency: "EUR" });
}

/** Ordina le dimensioni esplorabili e rende esplicita la loro incidenza sul totale. */
export function buildExplorerRows(input: ExplorerRowsInput): ExplorerRow[] {
  return [...input.categories]
    .sort((left, right) => right.amount - left.amount)
    .map((entry) => {
      const percentage = input.totalAmount > 0 ? (entry.amount / input.totalAmount) * 100 : null;
      return {
        label: entry.name,
        amount: entry.amount,
        secondaryLabel: `${entry.count} operazion${entry.count === 1 ? "e" : "i"}`,
        incidenceLabel: percentage !== null
          ? `Incide per il ${Math.round(percentage)}% sul totale speso nel periodo selezionato`
          : "Nessuna incidenza disponibile",
        percentage: percentage ?? undefined,
      };
    });
}

/** Restituisce una porzione dell'elenco Esplora, senza nascondere le righe successive. */
export function getExplorerPage<T>(items: T[], limit: number, offset = 0): ExplorerPage<T> {
  const safeLimit = Math.max(1, limit);
  const safeOffset = Math.max(0, offset);
  return {
    items: items.slice(safeOffset, safeOffset + safeLimit),
    hasMore: safeOffset + safeLimit < items.length,
  };
}

/** Suggerisce un budget iniziale solo quando non ne esiste già uno. */
export function buildCategoryDetail(input: { category: string; average: number; budget?: number }): CategoryDetail {
  return {
    category: input.category,
    budgetPrompt: input.budget && input.budget > 0 ? null : { suggestedAmount: input.average },
  };
}

/** Traduce la previsione già calcolata dal server nel modello di visualizzazione. */
export function buildMonthEndProjection(input: {
  currentNet: number;
  forecast?: MonthEndForecast | null;
}): MonthEndProjection | null {
  if (!input.forecast) return null;
  return {
    currentAmount: input.currentNet,
    projectedEndAmount: input.forecast.projected_end_amount,
    remainingExpectedIncome: input.forecast.remaining_expected_income,
  };
}

/** Confronta il risparmio del mese in corso con il mese precedente. */
export function buildMonthlySavingsComparison(
  entries: SavingsEntry[],
  currentPeriodKey = currentCalendarPeriodKey(),
): MonthlySavingsComparison | null {
  const [year, month] = currentPeriodKey.split("-").map(Number);
  if (!Number.isInteger(year) || !Number.isInteger(month) || month < 1 || month > 12) return null;
  const previousDate = new Date(year, month - 2, 1);
  const previousPeriodKey = `${previousDate.getFullYear()}-${String(previousDate.getMonth() + 1).padStart(2, "0")}`;
  const previous = entries.find((entry) => entry.period_key === previousPeriodKey);
  const current = entries.find((entry) => entry.period_key === currentPeriodKey);
  if (!previous || !current) return null;

  const delta = Number((current.net - previous.net).toFixed(2));
  return {
    direction: delta > 0 ? "up" : delta < 0 ? "down" : "flat",
    currentAmount: current.net,
    previousAmount: previous.net,
    delta,
  };
}

/** Confronta le due mensilità ricevute dall'API e restituisce le variazioni maggiori. */
export function buildSpendingChanges(entries: SpendingChangeEntry[]): SpendingChange[] {
  // Il backend restituisce i mesi in ordine cronologico: il secondo è il corrente.
  const months: string[] = [];
  for (const entry of entries) {
    if (!months.includes(entry.month)) months.push(entry.month);
    if (months.length === 2) break;
  }
  if (months.length < 2) return [];

  const [previousMonth, currentMonth] = months;
  const current = new Map<string, number>();
  const previous = new Map<string, number>();
  for (const entry of entries) {
    const target = entry.month === currentMonth
      ? current
      : entry.month === previousMonth ? previous : null;
    if (target) target.set(entry.name, (target.get(entry.name) ?? 0) + entry.amount);
  }

  return [...current.entries()]
    .map(([label, amount]): SpendingChange => {
      return { label, amount, increase: amount - (previous.get(label) ?? 0) };
    })
    .filter((entry) => entry.increase !== 0)
    .sort((left, right) => Math.abs(right.increase) - Math.abs(left.increase));
}

/** Confronta il totale speso del mese in corso con la mensilità precedente. */
export function buildMonthlySpendingTrend(input: {
  currentTotal: number;
  entries: SpendingChangeEntry[];
}): MonthlySpendingTrend | null {
  const months = [...new Set(input.entries.map((entry) => entry.month))];
  const previousMonth = months.length >= 2
    ? months[0]
    : input.currentTotal === 0 ? months[0] : null;
  if (!previousMonth) return null;

  const previousTotal = input.entries
    .filter((entry) => entry.month === previousMonth)
    .reduce((total, entry) => total + entry.amount, 0);
  if (previousTotal <= 0) return null;

  const difference = input.currentTotal - previousTotal;
  return {
    direction: difference > 0 ? "up" : difference < 0 ? "down" : "flat",
    percentage: Math.round(Math.abs(difference / previousTotal) * 100),
    previousTotal,
  };
}

/** Gruppi proponibili come destinazione di un'unione.
 *
 * Il merge è ammesso solo dentro la stessa categoria (stesso guardrail del
 * raggruppamento automatico), quindi i candidati di un'altra categoria non vanno
 * nemmeno mostrati: proporli porterebbe a un errore garantito dal server. */
export function buildMergeCandidates(
  clusters: ExpenseLabelCluster[],
  currentClusterId: number,
  categoryId: number | null,
): ExpenseLabelCluster[] {
  return clusters
    .filter((cluster) => cluster.id !== currentClusterId && cluster.category_id === categoryId)
    .sort((left, right) => right.total - left.total);
}
