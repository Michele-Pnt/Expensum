"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import Link from "next/link";

import { buildHeaders } from "@/lib/apiHeaders";
import { buildMerchantsByNameHref } from "@/lib/contextual-navigation";
import {
  buildMonthAvailability,
  buildRecentMovements,
  formatMonthLabel,
  type CategoryBudget,
  type ExpenseRow,
  type IncomeRow,
  type MonthAvailability,
  type RecentMovement,
} from "./homeViewModels";
import styles from "./home.module.css";

const RECENT_MOVEMENTS_LIMIT = 5;

function formatCurrency(amount: number): string {
  return amount.toLocaleString("it-IT", { style: "currency", currency: "EUR" });
}

function monthRange(today: Date): { start: string; end: string } {
  const start = new Date(today.getFullYear(), today.getMonth(), 1);
  const toIso = (date: Date) =>
    `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, "0")}-${String(date.getDate()).padStart(2, "0")}`;
  return { start: toIso(start), end: toIso(today) };
}

/** Home: quanto resta questo mese e cosa è successo di recente. */
export default function HomePage() {
  const [availability, setAvailability] = useState<MonthAvailability | null>(null);
  const [movements, setMovements] = useState<RecentMovement[] | null>(null);
  const [loadFailed, setLoadFailed] = useState(false);

  const monthLabel = useMemo(() => formatMonthLabel(new Date()), []);

  const loadSummary = useCallback(async (isCancelled: () => boolean) => {
    const headers = await buildHeaders();
    const { start, end } = monthRange(new Date());
    const listParams = `start=${start}&end=${end}&limit=${RECENT_MOVEMENTS_LIMIT}&sort_by=date&sort_dir=desc`;

    const [categories, budgets, preferences, expenses, incomes] = await Promise.all([
      fetch("/api/analytics/categories-expense?months=1", { credentials: "same-origin", headers }),
      fetch("/api/analytics/budget-status", { credentials: "same-origin", headers }),
      fetch("/api/user/preferences", { credentials: "same-origin", headers }),
      fetch(`/api/space/expenses?${listParams}`, { credentials: "same-origin", headers }),
      fetch(`/api/space/incomes?${listParams}`, { credentials: "same-origin", headers }),
    ]);

    const categoriesData = categories.ok
      ? ((await categories.json()) as { by_category?: { amount: number }[] })
      : { by_category: [] };
    const budgetData = budgets.ok
      ? ((await budgets.json()) as { budget_status?: CategoryBudget[] })
      : { budget_status: [] };
    const preferencesData = preferences.ok
      ? ((await preferences.json()) as { monthly_budget?: number | string | null })
      : { monthly_budget: null };
    const expensesData = expenses.ok ? ((await expenses.json()) as { expenses?: ExpenseRow[] }) : { expenses: [] };
    const incomesData = incomes.ok ? ((await incomes.json()) as { incomes?: IncomeRow[] }) : { incomes: [] };

    if (isCancelled()) return;

    const spentByCategory = Array.isArray(categoriesData.by_category) ? categoriesData.by_category : [];
    setAvailability(
      buildMonthAvailability({
        monthlyBudget:
          preferencesData.monthly_budget == null ? null : Number(preferencesData.monthly_budget),
        totalSpent: spentByCategory.reduce((total, category) => total + category.amount, 0),
        categoryBudgets: Array.isArray(budgetData.budget_status) ? budgetData.budget_status : [],
      }),
    );
    setMovements(
      buildRecentMovements({
        expenses: Array.isArray(expensesData.expenses) ? expensesData.expenses : [],
        incomes: Array.isArray(incomesData.incomes) ? incomesData.incomes : [],
        limit: RECENT_MOVEMENTS_LIMIT,
      }),
    );
  }, []);

  useEffect(() => {
    let cancelled = false;
    const run = async () => {
      try {
        await loadSummary(() => cancelled);
      } catch {
        if (!cancelled) setLoadFailed(true);
      }
    };
    void run();
    return () => {
      cancelled = true;
    };
  }, [loadSummary]);

  return (
    <div className={styles.page}>
      <header className={styles.header}>
        <p className={styles.month}>{monthLabel}</p>
        <h1 className={styles.title}>Home</h1>
      </header>

      {loadFailed && (
        <p className={styles.muted} role="status">
          Non riesco a caricare il riepilogo del mese. Controlla la connessione e ricarica la pagina.
        </p>
      )}

      <section className={styles.cards} aria-label="Riepilogo del mese" data-tour="home-summary">
        <div className={styles.card}>
          <p className={styles.cardLabel}>Disponibilità del mese</p>
          {availability === null ? (
            <div className={styles.skeleton} aria-hidden="true" />
          ) : availability.budget === null ? (
            <>
              <p className={styles.amount}>{formatCurrency(availability.spent)}</p>
              <p className={styles.muted}>
                Speso questo mese. Imposta un budget mensile in Gestisci per vedere quanto ti resta.
              </p>
            </>
          ) : (
            <>
              <p className={styles.amount}>{formatCurrency(availability.budget)}</p>
              <div
                className={styles.progressTrack}
                role="progressbar"
                aria-valuemin={0}
                aria-valuemax={100}
                aria-valuenow={Math.round((availability.progress ?? 0) * 100)}
                aria-label="Budget del mese consumato"
              >
                <div
                  className={styles.progressFill}
                  style={{ width: `${(availability.progress ?? 0) * 100}%` }}
                />
              </div>
              {availability.isOverBudget ? (
                <p className={styles.negative}>
                  {formatCurrency(Math.abs(availability.remaining ?? 0))} oltre il budget
                </p>
              ) : (
                <p className={styles.positive}>
                  {formatCurrency(availability.remaining ?? 0)} ancora disponibili
                </p>
              )}
            </>
          )}
        </div>
      </section>

      <section aria-labelledby="home-recent-movements">
        <div className={styles.sectionHeader}>
          <h2 className={styles.sectionTitle} id="home-recent-movements">Ultimi movimenti</h2>
          {/* Porta all'elenco completo delle voci, non raggruppate: è la vista che
              mostra i movimenti con il nome esatto con cui sono stati registrati. */}
          <Link href={buildMerchantsByNameHref()} className={styles.sectionLink}>Vedi tutto</Link>
        </div>

        {movements === null ? (
          <div className={styles.skeleton} aria-hidden="true" />
        ) : movements.length === 0 ? (
          <p className={styles.empty}>
            Nessun movimento questo mese. Tocca <strong>Registra</strong> per aggiungerne uno.
          </p>
        ) : (
          <ul className={styles.movements}>
            {movements.map((movement) => (
              <li key={movement.key} className={styles.movement}>
                <span className={styles.movementName}>
                  {movement.name}
                  <span className={styles.movementCategory}>{movement.label}</span>
                </span>
                <span
                  className={
                    movement.direction === "in"
                      ? `${styles.movementAmount} ${styles.amountIn}`
                      : `${styles.movementAmount} ${styles.amountOut}`
                  }
                >
                  {movement.direction === "in" ? "+ " : "− "}
                  {formatCurrency(movement.amount)}
                </span>
              </li>
            ))}
          </ul>
        )}
      </section>
    </div>
  );
}
