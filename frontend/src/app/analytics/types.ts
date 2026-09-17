export type AnalyticsPeriod = "current" | "three_months" | "year" | "custom";

export type ExplorerDimension = "categories" | "merchants" | "accounts";

export type AnalyticsDestination = "today" | "explore" | "plan";

export type AnalyticsSelection = {
  category?: string;
  merchant?: string;
  account?: string;
};

/** Riga del grafico "Dove hai speso di più" / dimensione "Voci".
 *
 * `cluster_id` è valorizzato solo quando tutte le spese della riga condividono lo
 * stesso gruppo: senza un gruppo unico la correzione manuale non ha un bersaglio,
 * e la UI nasconde "Unisci"/"Dividi". */
export type Merchant = {
  name: string;
  total: number;
  count: number;
  category: string;
  cluster_id?: number | null;
  category_id?: number | null;
};

/** Spesa mostrata espandendo una voce: anteprima, non l'elenco completo. */
export type LabelExpense = { id: number; name: string; date: string; amount: number };

/** Voce dentro un gruppo, con le spese che la compongono.
 *
 * L'unità di selezione è la voce, non la singola spesa: le spese scritte allo stesso
 * modo si spostano sempre insieme, altrimenti nessuna regola potrebbe descriverle. */
export type LabelVariant = {
  text: string;
  count: number;
  total: number;
  /** Assente nella lista dei candidati: si carica aprendo il gruppo. */
  expenses?: LabelExpense[];
};

/** Gruppo di voci candidato all'unione (endpoint /api/expense-labels/clusters). */
export type ExpenseLabelCluster = {
  id: number;
  anchor_text: string;
  category_id: number | null;
  category: string;
  total: number;
  count: number;
  variants: LabelVariant[];
};

export type SavingsEntry = {
  month: string;
  /** Chiave calendario `YYYY-MM` restituita dall'overview mensile. */
  period_key?: string;
  income: number;
  expenses: number;
  net: number;
};

/** Previsione lato server per la parte residua del mese in corso. */
export type MonthEndForecast = {
  variable_expense_projection: number;
  scheduled_expenses: number;
  remaining_expected_income: number;
  projected_end_amount: number;
};

export type BudgetStatusEntry = {
  category: string;
  budget: number;
  spent: number;
  remaining: number;
  percentage: number;
};

export type BudgetStatusSummary = {
  budget_status: BudgetStatusEntry[];
  monthly_budget: number | string | null;
  total_spent: number;
};
