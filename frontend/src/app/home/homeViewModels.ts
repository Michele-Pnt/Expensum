/** View model della Home: riepilogo del mese e ultimi movimenti. */

export interface CategoryBudget {
  budget: number;
  spent: number;
}

export interface ExpenseRow {
  id: number;
  date: string;
  name: string;
  amount: number;
  category?: string | null;
}

export interface IncomeRow {
  id: number;
  date: string;
  name: string;
  amount: number;
  income_type?: string | null;
  income_category?: string | null;
}

export interface MonthAvailability {
  /** Budget del mese: null quando l'utente non ne ha impostato nessuno. */
  budget: number | null;
  spent: number;
  remaining: number | null;
  /** Quota di budget consumata, 0-1: null senza budget. */
  progress: number | null;
  isOverBudget: boolean;
}

export interface RecentMovement {
  key: string;
  name: string;
  label: string;
  amount: number;
  date: string;
  direction: "in" | "out";
}

const MONTH_NAMES = [
  "gennaio", "febbraio", "marzo", "aprile", "maggio", "giugno",
  "luglio", "agosto", "settembre", "ottobre", "novembre", "dicembre",
];

export function formatMonthLabel(date: Date): string {
  return `${MONTH_NAMES[date.getMonth()]} ${date.getFullYear()}`.toUpperCase();
}

/**
 * Stessa priorità della card "Budget disponibile" di Analytics: budget mensile
 * generale se impostato, altrimenti somma dei budget di categoria.
 */
export function buildMonthAvailability(input: {
  monthlyBudget: number | null;
  totalSpent: number;
  categoryBudgets: CategoryBudget[];
}): MonthAvailability {
  const { monthlyBudget, totalSpent, categoryBudgets } = input;

  const hasMonthlyBudget = monthlyBudget != null && Number.isFinite(monthlyBudget) && monthlyBudget > 0;
  const categoryTotal = categoryBudgets.reduce((total, item) => total + item.budget, 0);
  const budget = hasMonthlyBudget ? monthlyBudget : categoryTotal > 0 ? categoryTotal : null;

  if (budget === null) {
    return { budget: null, spent: totalSpent, remaining: null, progress: null, isOverBudget: false };
  }

  // Il budget mensile generale si confronta con la spesa totale del mese; la somma
  // dei budget di categoria invece solo con la spesa delle categorie che un budget
  // ce l'hanno — altrimenti una categoria senza budget consumerebbe quello altrui e
  // la Home mostrerebbe un residuo di segno opposto a quello di Analytics.
  const spentAgainstBudget = hasMonthlyBudget
    ? totalSpent
    : categoryBudgets.reduce((total, item) => total + item.spent, 0);

  const remaining = round2(budget - spentAgainstBudget);
  return {
    budget,
    spent: spentAgainstBudget,
    remaining,
    // Il riempimento resta tra 0 e 100%: oltre il budget lo dice il testo, e un
    // mese con più rimborsi che spese non deve produrre una barra negativa.
    progress: Math.min(1, Math.max(0, round4(spentAgainstBudget / budget))),
    isOverBudget: remaining < 0,
  };
}

export function buildRecentMovements(input: {
  expenses: ExpenseRow[];
  incomes: IncomeRow[];
  limit: number;
}): RecentMovement[] {
  const expenses: RecentMovement[] = input.expenses.map((expense) => ({
    key: `expense-${expense.id}`,
    name: expense.name,
    label: expense.category || "Senza categoria",
    amount: expense.amount,
    date: expense.date,
    direction: "out",
  }));

  const incomes: RecentMovement[] = input.incomes.map((income) => ({
    key: `income-${income.id}`,
    name: income.name,
    label: income.income_category || income.income_type || "Entrate",
    amount: income.amount,
    date: income.date,
    direction: "in",
  }));

  return [...expenses, ...incomes]
    .sort((a, b) => b.date.localeCompare(a.date))
    .slice(0, input.limit);
}

function round2(value: number): number {
  return Math.round(value * 100) / 100;
}

function round4(value: number): number {
  return Math.round(value * 10000) / 10000;
}
