type BudgetLike = {
  monthly_budget: number | string | null;
};

type MonthlyBudgetGuidance = {
  categoryBudgetTotal: number;
  suggestedBudget: number | null;
  hasCategoryBudgets: boolean;
};

type MonthlyBudgetValidation =
  | { ok: true; value: number | null }
  | { ok: false; error: string };

const MINIMUM_ERROR = "Il budget mensile generale non puo' essere minore della somma dei budget categoria.";

export function buildMonthlyBudgetGuidance(categories: BudgetLike[]): MonthlyBudgetGuidance {
  const categoryBudgetTotal = categories.reduce((total, category) => {
    const budget = Number(category.monthly_budget ?? 0);
    return budget > 0 ? total + budget : total;
  }, 0);

  return {
    categoryBudgetTotal,
    suggestedBudget: categoryBudgetTotal > 0 ? categoryBudgetTotal : null,
    hasCategoryBudgets: categoryBudgetTotal > 0,
  };
}

export function validateGeneralMonthlyBudget(
  rawBudget: string,
  minimumBudget: number,
): MonthlyBudgetValidation {
  const trimmed = rawBudget.trim();
  if (!trimmed) return { ok: true, value: null };

  const value = Number(trimmed);
  if (!Number.isFinite(value) || value < 0) {
    return { ok: false, error: "Inserisci un budget mensile valido." };
  }
  if (minimumBudget > 0 && value < minimumBudget) {
    return { ok: false, error: MINIMUM_ERROR };
  }

  return { ok: true, value };
}
