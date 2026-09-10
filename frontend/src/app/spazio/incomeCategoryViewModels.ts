/** Stable client-side representation of dual-read income category payloads. */
export type IncomeCategoryDto = {
  id: number;
  name: string;
  monthly_budget: number | null;
  description?: string | null;
  average: number;
  archived: boolean;
};

export type IncomeCategoryTransaction = {
  date: string;
  income_category?: string | { name?: string | null } | null;
  income_type?: string | null;
};

/** Keep all persisted income categories selectable. */
export function activeIncomeCategories(categories: IncomeCategoryDto[]): IncomeCategoryDto[] {
  return categories;
}

/** Prefer the structured category while legacy records still expose income_type. */
export function incomeCategoryLabel(transaction: IncomeCategoryTransaction): string {
  const category = transaction.income_category;
  if (typeof category === "string" && category.trim()) return category;
  if (typeof category === "object" && category?.name?.trim()) return category.name;
  return transaction.income_type?.trim() || "Altra entrata";
}

/** Render API ISO dates without timezone conversion. */
export function formatIncomeDate(value: string): string {
  const [year = "", month = "", day = ""] = value.slice(0, 10).split("-");
  return year && month && day ? `${day}-${month}-${year}` : value;
}
