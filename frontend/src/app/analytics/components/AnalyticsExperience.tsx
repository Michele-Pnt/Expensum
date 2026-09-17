"use client";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Alert, Box, Button, Card, CardContent, CircularProgress, Snackbar, Typography } from "@mui/material";
import AnalyticsExplorer, { type ExplorerTransaction } from "./AnalyticsExplorer";
import LabelFixDialog, { type LabelFixMode, type LabelFixTarget } from "./LabelFixDialog";
import AnalyticsNavigation from "./AnalyticsNavigation";
import AnalyticsPeriodPicker from "./AnalyticsPeriodPicker";
import AnalyticsPlanner from "./AnalyticsPlanner";
import AnalyticsToday from "./AnalyticsToday";
import InfoButton from "../../../components/InfoButton";
import type { AnalyticsDestination, AnalyticsPeriod, AnalyticsSelection, ExplorerDimension, Merchant, MonthEndForecast, SavingsEntry } from "../types";
import { buildExplorerRows, buildMonthEndProjection, buildMonthlySavingsComparison, buildSpendingChanges, buildTodaySummary, currentCalendarPeriodKey, getExplorerPage, periodToMonths } from "../viewModels";
import { getCsrfToken } from "@/lib/csrf";

type Category = { month: string; name: string; amount: number; count?: number };
type AccountMonth = { month: string; account: string; amount: number; count?: number };
type Account = { name: string; balance: number };
type Budget = { category: string; budget: number; spent: number; remaining: number; percentage: number };
type Transaction = { id: number; date: string; name: string; normalized_name?: string; amount: number; category: string; account: string };
type TransactionsResponse = { transactions: Transaction[]; total: number };
type BudgetStatusResponse = { budget_status: Budget[]; monthly_budget?: number | string | null; total_spent?: number };
type UserPreferencesResponse = { monthly_budget?: number | string | null; analytics_group_labels?: boolean };
type ApiState = { savings: SavingsEntry[]; categories: Category[]; comparisons: Category[]; accounts: AccountMonth[]; wealth: Account[]; merchants: Merchant[]; budgets: Budget[]; monthlyBudget: number | string | null; totalSpent: number; planType: string; monthEndForecast?: MonthEndForecast | null };
type TelegramWindow = Window & { Telegram?: { WebApp?: { initData?: string } } };
const EXPLORER_PAGE_SIZE = 20;
const initDataOf = (): string | undefined => (window as TelegramWindow).Telegram?.WebApp?.initData;
const headers = (): HeadersInit => { const initData = initDataOf(); return initData ? { "X-Telegram-Init-Data": initData } : {}; };
async function getJson<T>(path: string): Promise<T> { const response = await fetch(path, { headers: headers(), credentials: "same-origin" }); if (!response.ok) throw new Error(`HTTP_${response.status}`); return response.json() as Promise<T>; }

type DeepLink = {
  destination: AnalyticsDestination;
  period: AnalyticsPeriod;
  dimension: ExplorerDimension;
  selection: AnalyticsSelection;
  /** `null` = usa la preferenza salvata dell'utente. */
  grouped: boolean | null;
};

/**
 * Legge la destinazione richiesta dall'URL (link contestuali da Home, Chat, report).
 *
 * Va letta in modo sincrono all'inizializzazione dello stato, non in un effetto:
 * il primo caricamento dipende da `groupLabels`, e impostarlo dopo il mount
 * farebbe partire una fetch con il raggruppamento sbagliato, la cui risposta
 * potrebbe poi sovrascrivere la scelta arrivata dal link.
 */
function readDeepLink(): DeepLink {
  const fallback: DeepLink = { destination: "today", period: "current", dimension: "categories", selection: {}, grouped: null };
  if (typeof window === "undefined") return fallback;

  const params = new URLSearchParams(window.location.search);
  const category = params.get("category");
  const merchant = params.get("merchant");
  const tab = params.get("tab");
  const group = params.get("group");

  const destination: AnalyticsDestination = tab === "plan"
    ? "plan"
    : tab === "expenses" || category || merchant ? "explore" : "today";
  const dimension: ExplorerDimension = merchant || params.get("dimension") === "merchants" ? "merchants" : "categories";
  const selection: AnalyticsSelection = merchant ? { merchant } : category ? { category } : {};

  return {
    destination,
    period: params.get("months") === "1" ? "current" : fallback.period,
    dimension,
    selection,
    grouped: group === "0" ? false : group === "1" ? true : null,
  };
}

/** Esperienza Analytics mobile-first che riusa le API e l'autenticazione della Mini App. */
export default function AnalyticsExperience({ onOpenAdvanced }: { onOpenAdvanced: () => void }) {
  const deepLink = readDeepLink();
  const [destination, setDestination] = useState<AnalyticsDestination>(deepLink.destination); const [period, setPeriod] = useState<AnalyticsPeriod>(deepLink.period); const [dimension, setDimension] = useState<ExplorerDimension>(deepLink.dimension); const [selection, setSelection] = useState<AnalyticsSelection>(deepLink.selection); const [state, setState] = useState<ApiState | null>(null); const [transactions, setTransactions] = useState<ExplorerTransaction[]>([]); const [transactionTotal, setTransactionTotal] = useState(0); const [transactionsLoading, setTransactionsLoading] = useState(false); const [visibleItemsLimit, setVisibleItemsLimit] = useState(EXPLORER_PAGE_SIZE); const [error, setError] = useState<string | null>(null); const [loading, setLoading] = useState(true);
  const transactionRequestId = useRef(0);
  // Raggruppamento voci: preferenza persistita lato server, quindi vale su ogni dispositivo.
  // `null` finché non è nota: evita di chiedere top-merchants con un default sbagliato.
  const [groupLabels, setGroupLabels] = useState<boolean | null>(deepLink.grouped);
  const [labelFix, setLabelFix] = useState<{ mode: LabelFixMode; target: LabelFixTarget } | null>(null);
  const [toast, setToast] = useState<string | null>(null);
  const cockpitLoad = useCallback(async () => {
    const months = periodToMonths(period);
    const overviewMonths = destination === "today" ? 2 : months;
    setLoading(true);
    setError(null);
    try {
      const groupParam = groupLabels === false ? "&group=0" : groupLabels === true ? "&group=1" : "";
      const [overview, categories, merchants, wealth, comparisons, preferences] = await Promise.all([
        getJson<{ savings: SavingsEntry[]; totals_by_account: AccountMonth[]; plan_type: string; month_end_forecast?: MonthEndForecast }>(`/api/analytics/overview?months=${overviewMonths}`),
        getJson<{ by_category: Category[] }>(`/api/analytics/categories-expense?months=${months}`),
        getJson<{ merchants: Merchant[]; grouped?: boolean }>(`/api/analytics/top-merchants?months=${months}${groupParam}`),
        getJson<{ accounts: Account[] }>("/api/analytics/wealth"),
        period === "current"
          ? getJson<{ by_category: Category[] }>("/api/analytics/categories-expense?months=2")
          : Promise.resolve({ by_category: [] }),
        getJson<UserPreferencesResponse>("/api/user/preferences"),
      ]);
      const budget: BudgetStatusResponse = overview.plan_type === "pro"
        ? await getJson<BudgetStatusResponse>("/api/analytics/budget-status")
        : { budget_status: [], total_spent: overview.savings.at(-1)?.expenses ?? 0 };
      setGroupLabels(merchants.grouped ?? preferences.analytics_group_labels ?? true);
      setState({
        savings: overview.savings,
        categories: categories.by_category,
        comparisons: comparisons.by_category,
        accounts: overview.totals_by_account,
        wealth: wealth.accounts,
        merchants: merchants.merchants,
        budgets: budget.budget_status,
        monthlyBudget: preferences.monthly_budget ?? budget.monthly_budget ?? null,
        totalSpent: budget.total_spent ?? overview.savings.at(-1)?.expenses ?? 0,
        planType: overview.plan_type,
        monthEndForecast: overview.month_end_forecast ?? null,
      });
    } catch (caught) {
      setError(caught instanceof Error && caught.message === "HTTP_401"
        ? "Sessione non valida: riapri la mini-app dal bot."
        : "Non è stato possibile aggiornare Analytics. Riprova tra poco.");
    } finally {
      setLoading(false);
    }
  }, [destination, period, groupLabels]);
  /** Salva la preferenza con aggiornamento ottimistico: se il server rifiuta si torna indietro. */
  const changeGrouping = useCallback(async (next: boolean) => { const previous = groupLabels; setGroupLabels(next); transactionRequestId.current += 1; setSelection({}); setTransactions([]); setTransactionTotal(0); try { const csrf = await getCsrfToken().catch(() => null); const response = await fetch("/api/user/preferences", { method: "PUT", credentials: "same-origin", headers: { "Content-Type": "application/json", ...headers(), ...(csrf ? { "X-CSRFToken": csrf } : {}) }, body: JSON.stringify({ analytics_group_labels: next }) }); if (!response.ok) throw new Error("preference_save_failed"); } catch { setGroupLabels(previous); setError("Non è stato possibile salvare la preferenza. Riprova."); } }, [groupLabels]);
  useEffect(() => { void cockpitLoad(); }, [cockpitLoad]);
  const currentPeriodKey = currentCalendarPeriodKey();
  const summary = useMemo(() => buildTodaySummary({ savings: state?.savings ?? [], budgetStatus: state?.budgets ?? [], monthlyBudget: state?.monthlyBudget ?? null, totalSpent: state?.totalSpent ?? 0, currentPeriodKey }), [currentPeriodKey, state]);
  const projection = useMemo(() => destination === "today" ? buildMonthEndProjection({ currentNet: summary.monthlySavings, forecast: state?.monthEndForecast }) : null, [destination, state, summary.monthlySavings]);
  const changes = useMemo(() => period === "current" ? buildSpendingChanges(state?.comparisons ?? []) : [], [period, state]);
  const savingsComparison = useMemo(() => destination === "today" ? buildMonthlySavingsComparison(state?.savings ?? [], currentPeriodKey) : null, [currentPeriodKey, destination, state]);
  const totalSpent = useMemo(() => state ? state.categories.reduce((sum, category) => sum + category.amount, 0) : 0, [state]);
  const items = useMemo(() => { if (!state) return []; if (dimension === "merchants") return state.merchants.map((m) => { const percentage = totalSpent > 0 ? (m.total / totalSpent) * 100 : 0; const operations = `${m.count} operazion${m.count === 1 ? "e" : "i"}`; return { label: m.name, amount: m.total, secondaryLabel: operations, incidenceLabel: totalSpent > 0 ? `Incide per il ${Math.round(percentage)}% sul totale speso nel periodo selezionato` : "Nessuna incidenza disponibile", percentage: totalSpent > 0 ? percentage : undefined, clusterId: m.cluster_id ?? null, categoryId: m.category_id ?? null }; }); const totals = new Map<string, { amount: number; count: number }>(); const rows = dimension === "accounts" ? state.accounts.map((a) => ({ name: a.account, amount: a.amount, count: a.count ?? 0 })) : state.categories.map((c) => ({ name: c.name, amount: c.amount, count: c.count ?? 0 })); rows.forEach((row) => { const existing = totals.get(row.name) ?? { amount: 0, count: 0 }; totals.set(row.name, { amount: existing.amount + row.amount, count: existing.count + row.count }); }); const entries = [...totals].map(([name, { amount, count }]) => ({ name, amount, count })); return buildExplorerRows({ dimension, totalAmount: entries.reduce((sum, entry) => sum + entry.amount, 0), categories: entries }); }, [dimension, state, totalSpent]);
  const selectedLabel = selection.category ?? selection.merchant ?? selection.account;
  const loadTransactions = useCallback(async (activeSelection: AnalyticsSelection, offset = 0) => { const requestId = ++transactionRequestId.current; const params = new URLSearchParams({ limit: String(EXPLORER_PAGE_SIZE), offset: String(offset) }); const today = new Date(); const months = periodToMonths(period); const start = new Date(today.getFullYear(), today.getMonth() - months + 1, 1); params.set("start", start.toISOString().slice(0, 10)); params.set("end", today.toISOString().slice(0, 10)); if (activeSelection.category) params.set("category", activeSelection.category); if (activeSelection.account) params.set("account", activeSelection.account); if (activeSelection.merchant) { params.set("merchant", activeSelection.merchant); params.set("group", groupLabels === false ? "0" : "1"); } setTransactionsLoading(true); try { const data = await getJson<TransactionsResponse>(`/api/analytics/transactions?${params}`); if (requestId === transactionRequestId.current) { setTransactions((current) => offset === 0 ? data.transactions : [...current, ...data.transactions]); setTransactionTotal(data.total); } } catch { if (requestId === transactionRequestId.current) setError("Non è stato possibile caricare le operazioni. Riprova."); } finally { if (requestId === transactionRequestId.current) setTransactionsLoading(false); } }, [period, groupLabels]);
  useEffect(() => { if (selectedLabel) void loadTransactions(selection); }, [loadTransactions, selectedLabel, selection]);
  const choose = (next: AnalyticsSelection) => { const nextLabel = next.category ?? next.merchant ?? next.account; setDestination("explore"); transactionRequestId.current += 1; if (selectedLabel === nextLabel) { setSelection({}); setTransactions([]); setTransactionTotal(0); setTransactionsLoading(false); return; } setSelection(next); setTransactions([]); setTransactionTotal(0); };
  const visibleItems = useMemo(() => getExplorerPage(items, visibleItemsLimit), [items, visibleItemsLimit]);
  const netWorth = state?.wealth.reduce((sum, account) => sum + account.balance, 0) ?? 0;

  return (
    <Box sx={{ width: "100%", maxWidth: 960, mx: "auto", p: { xs: 1.5, sm: 3 }, display: "grid", gap: 2 }}>
      <Box>
        <Typography component="h1" variant="h5" color="primary" fontWeight={300}>Analytics</Typography>
        <Typography variant="body2" color="text.secondary">Capisci, esplora e pianifica senza perderti nei grafici.</Typography>
      </Box>
      <AnalyticsNavigation destination={destination} onDestinationChange={(next) => { setDestination(next); if (next !== "explore") { transactionRequestId.current += 1; setPeriod("current"); setSelection({}); setTransactions([]); setTransactionTotal(0); setTransactionsLoading(false); } }} />
      {destination === "explore" && (
        <AnalyticsPeriodPicker period={period} onPeriodChange={(next) => { transactionRequestId.current += 1; setPeriod(next); setSelection({}); setTransactions([]); setTransactionTotal(0); setVisibleItemsLimit(EXPLORER_PAGE_SIZE); setTransactionsLoading(false); }} />
      )}
      {error && <Alert severity="error" action={<Button color="inherit" size="small" onClick={() => void cockpitLoad()}>Riprova</Button>}>{error}</Alert>}
      {loading && <Box py={6} textAlign="center" role="status" aria-live="polite"><CircularProgress /><Typography>Caricamento Analytics</Typography></Box>}
      {!loading && state && destination === "today" && (
        <>
          <AnalyticsToday summary={summary} projection={projection} changes={changes} savingsComparison={savingsComparison} showAttentions={period === "current"} onSelect={choose} />
          <Card>
            <CardContent>
              <Box display="flex" alignItems="center">
                <Typography variant="subtitle2" fontWeight={600}>Salute finanziaria</Typography>
                <InfoButton label="Come calcoliamo Salute finanziaria" explanation="È la somma dei saldi attuali dei conti collegati. Non include contanti, investimenti o conti che non hai collegato a Expensum." />
              </Box>
              <Typography variant="h5" mt={1}>{netWorth.toLocaleString("it-IT", { style: "currency", currency: "EUR" })}</Typography>
              <Typography variant="body2" color="text.secondary">Patrimonio sui conti · {state.wealth.length} conti collegati</Typography>
              <Button variant="text" sx={{ minHeight: 44, mt: 1 }} onClick={onOpenAdvanced}>Apri analisi dettagliate</Button>
            </CardContent>
          </Card>
        </>
      )}
      {!loading && state && destination === "explore" && (
        <>
          <AnalyticsExplorer
            dimension={dimension}
            expandedItem={selectedLabel ?? null}
            items={visibleItems.items}
            totalSpent={totalSpent}
            transactions={transactions}
            transactionsLoading={transactionsLoading}
            hasMoreItems={visibleItems.hasMore}
            hasMoreTransactions={transactions.length < transactionTotal}
            onDimensionChange={(next) => { transactionRequestId.current += 1; setDimension(next); setSelection({}); setTransactions([]); setTransactionTotal(0); setVisibleItemsLimit(EXPLORER_PAGE_SIZE); setTransactionsLoading(false); }}
            onSelect={choose}
            onLoadMoreItems={() => setVisibleItemsLimit((current) => current + EXPLORER_PAGE_SIZE)}
            onLoadMoreTransactions={() => void loadTransactions(selection, transactions.length)}
            grouped={groupLabels ?? true}
            onGroupedChange={(next) => void changeGrouping(next)}
            onFixLabel={(mode, target) => setLabelFix({ mode, target })}
          />
          {items.length === 0 && <Alert severity="info">Non ci sono ancora movimenti per questo periodo.</Alert>}
        </>
      )}
      {!loading && state && destination === "plan" && <AnalyticsPlanner budgets={state.budgets} isPro={state.planType === "pro"} />}
      <LabelFixDialog
        open={labelFix !== null}
        mode={labelFix?.mode ?? "merge"}
        target={labelFix?.target ?? null}
        months={periodToMonths(period)}
        initData={typeof window === "undefined" ? undefined : initDataOf()}
        onClose={() => setLabelFix(null)}
        onDone={(message) => {
          // Dopo una correzione l'etichetta selezionata può non esistere più:
          // si azzera la selezione e si ricarica, invece di mostrare un vuoto.
          transactionRequestId.current += 1;
          setSelection({});
          setTransactions([]);
          setToast(message);
          void cockpitLoad();
        }}
      />
      <Snackbar
        open={toast !== null}
        autoHideDuration={3000}
        onClose={() => setToast(null)}
        message={toast ?? ""}
        anchorOrigin={{ vertical: "bottom", horizontal: "center" }}
      />
    </Box>
  );
}
