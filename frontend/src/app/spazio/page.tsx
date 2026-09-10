"use client";

import { useEffect, useState, useCallback, useMemo } from "react";
import {
  Box, Card, CardContent, Tab, Tabs, Typography, TablePagination,
  IconButton, Button, Dialog, DialogTitle, DialogContent, DialogActions,
  TextField, Select, MenuItem, FormControl, InputLabel, Chip, Menu, Divider,
  CircularProgress, Alert, Tooltip, ToggleButton, ToggleButtonGroup,
  useMediaQuery, useTheme,
} from "@mui/material";
import {
  Plus, Pencil, Trash2, Check, X, CalendarDays,
  Landmark, Tag, CreditCard, ArrowDownCircle, ArrowUpCircle, ArrowLeftRight,
} from "lucide-react";
import { apiFetch, apiErrorMessage } from "@/lib/api";
import { formatDateIt } from "@/lib/date";
import {
  buildMonthlyBudgetGuidance,
  validateGeneralMonthlyBudget,
} from "./budgetViewModels";
import {
  activeIncomeCategories,
  incomeCategoryLabel,
  type IncomeCategoryDto,
} from "./incomeCategoryViewModels";
import ResponsiveDataTable, { type Column } from "./components/ResponsiveDataTable";
import SwipeCalendar from "@/components/SwipeCalendar";
import InfoButton from "@/components/InfoButton";
import { useSnackbar } from "@/components/feedback/useSnackbar";
import AppSnackbar from "@/components/feedback/AppSnackbar";

// ---------------------------------------------------------------------------
// Tipi
// ---------------------------------------------------------------------------

interface Account {
  id: number; name: string; account_type: string | null;
  current_balance: number; opening_balance: number; currency: string;
}
interface Category { id: number; name: string; monthly_budget: number | null; description?: string | null }
interface Subscription {
  id: number; name: string; amount: number | null; sub_type: string | null;
  last_billed: string | null; account_id: number | null; account_name: string;
  category_id: number | null;
}
interface Expense {
  id: number; date: string; name: string; amount: number;
  category: string; category_id: number | null;
  account: string; account_id: number | null;
}
interface Income {
  id: number; date: string; name: string; amount: number;
  income_type: string; income_category?: string | null; income_category_id?: number | null;
  account: string; account_id: number | null;
}
interface Transfer {
  id: number; date: string; name: string; amount: number;
  from_account_id: number; to_account_id: number;
}
interface UserPreferencesResponse { monthly_budget: number | string | null }

type DialogMode = "add" | "edit";
type EntityType = "account" | "category" | "incomeCategory" | "subscription" | "expense" | "income" | "transfer";

// ---------------------------------------------------------------------------
// Colori / costanti
// ---------------------------------------------------------------------------

const PRIMARY = "#5FC4CB";
// Rosso del tema (theme.palette.error.main), non un rosso ad-hoc: contrasto già
// verificato contro lo sfondo #1C363D, coerente col resto dell'app.
const ACCENT = "#DC2626";
// Verde del tema (theme.palette.success.main): cifre delle entrate, per distinguerle
// a colpo d'occhio dalle spese (rosse) e dal budget (azzurrino).
const INCOME_COLOR = "#16A34A";
const BORDER = "rgba(176,181,185,0.25)";
// theme.palette.text.secondary: unico grigio per testo secondario/placeholder,
// non più due varianti (#9CA3AF/#B0B5B9) senza motivo di contrasto.
const MUTED = "#B0B5B9";

const ENTITY_PATH: Record<EntityType, string> = {
  account: "accounts",
  category: "categories",
  incomeCategory: "income-categories",
  subscription: "subscriptions",
  expense: "expenses",
  income: "incomes",
  transfer: "transfers",
};

const ACCOUNT_TYPES = ["Conto corrente", "Carta di credito", "Risparmio", "Contanti", "Investimento"];
const SUB_TYPES = ["Settimanale", "Mensile", "Bimestrale", "Trimestrale", "Semestrale", "Annuale"];

// Su mobile la tab bar diventa una griglia di sole icone (senza etichette visibili,
// solo aria-label) per evitare lo scroll orizzontale con 6 sezioni. Stesso ordine dei <Tab>.
const SPAZIO_TAB_ICONS = [
  { label: "Conti", Icon: Landmark },
  { label: "Categorie", Icon: Tag },
  { label: "Abbonamenti", Icon: CreditCard },
  { label: "Spese", Icon: ArrowUpCircle },
  { label: "Entrate", Icon: ArrowDownCircle },
  { label: "Trasferimenti", Icon: ArrowLeftRight },
];

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function fmtCurrency(n: number | null | undefined): string {
  if (n == null) return "—";
  return n.toLocaleString("it-IT", { style: "currency", currency: "EUR" });
}

/** Come fmtCurrency ma con segno esplicito anche per i positivi: il colore da solo
 * (verde/rosso) non basta a comunicare la direzione a chi non lo percepisce. */
function fmtSignedCurrency(n: number | null | undefined): string {
  if (n == null) return "—";
  const formatted = fmtCurrency(Math.abs(n));
  return n >= 0 ? `+${formatted}` : `−${formatted}`;
}

function todayIso(): string {
  return new Date().toISOString().slice(0, 10);
}

function monthStartIso(): string {
  const d = new Date();
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-01`;
}

function toIso(d: Date): string {
  return d.toISOString().slice(0, 10);
}

function daysAgoIso(days: number): string {
  const d = new Date();
  d.setDate(d.getDate() - days);
  return toIso(d);
}

function prevMonthStartIso(): string {
  const d = new Date();
  return toIso(new Date(d.getFullYear(), d.getMonth() - 1, 1));
}

function prevMonthEndIso(): string {
  const d = new Date();
  return toIso(new Date(d.getFullYear(), d.getMonth(), 0));
}

function yearStartIso(): string {
  return `${new Date().getFullYear()}-01-01`;
}

const DATE_RANGE_PRESETS = [
  { label: "Questo mese", start: monthStartIso, end: todayIso },
  { label: "Mese scorso", start: prevMonthStartIso, end: prevMonthEndIso },
  { label: "Ultimi 7 giorni", start: () => daysAgoIso(7), end: todayIso },
  { label: "Ultimi 30 giorni", start: () => daysAgoIso(30), end: todayIso },
  { label: "Anno in corso", start: yearStartIso, end: todayIso },
];

// ---------------------------------------------------------------------------
// Componente principale
// ---------------------------------------------------------------------------

export default function SpazioPage() {
  const theme = useTheme();
  const isMobile = useMediaQuery(theme.breakpoints.down("sm"));
  const [tab, setTab] = useState(0);
  const [categoryKind, setCategoryKind] = useState<"expense" | "income">("expense");

  useEffect(() => {
    const params = new URLSearchParams(window.location.search);
    if (params.get("tab") === "transfers") {
      setTab(5);
    } else if (params.get("tab") === "expenses") {
      setTab(3);
      const search = params.get("search");
      if (search) setExpSearch(search);
    }
  }, []);

  // Dati
  const [accounts, setAccounts] = useState<Account[]>([]);
  const [categories, setCategories] = useState<Category[]>([]);
  const [subscriptions, setSubscriptions] = useState<Subscription[]>([]);
  const [expenses, setExpenses] = useState<Expense[]>([]);
  const [incomes, setIncomes] = useState<Income[]>([]);
  const [incomeCategories, setIncomeCategories] = useState<IncomeCategoryDto[]>([]);
  const [transfers, setTransfers] = useState<Transfer[]>([]);

  // Paginazione spese/entrate
  const [expPage, setExpPage] = useState(0);
  const [expRowsPP, setExpRowsPP] = useState(25);
  const [expTotal, setExpTotal] = useState(0);
  const [incPage, setIncPage] = useState(0);
  const [incRowsPP, setIncRowsPP] = useState(25);
  const [incTotal, setIncTotal] = useState(0);

  // Filtri data
  const [expStart, setExpStart] = useState(monthStartIso());
  const [expEnd, setExpEnd] = useState(todayIso());
  const [incStart, setIncStart] = useState(monthStartIso());
  const [incEnd, setIncEnd] = useState(todayIso());

  // Spese: filtri extra + sort (server-side)
  const [expSearch, setExpSearch] = useState("");
  const [expCatId, setExpCatId] = useState("");
  const [expAccId, setExpAccId] = useState("");
  const [expSortBy, setExpSortBy] = useState("date");
  const [expSortDir, setExpSortDir] = useState<"asc" | "desc">("desc");

  // Entrate: filtri extra + sort (server-side)
  const [incSearch, setIncSearch] = useState("");
  const [incCategoryId, setIncCategoryId] = useState("");
  const [incAccId, setIncAccId] = useState("");
  const [incSortBy, setIncSortBy] = useState("date");
  const [incSortDir, setIncSortDir] = useState<"asc" | "desc">("desc");

  // Abbonamenti: filtri client-side
  const [subSearch, setSubSearch] = useState("");
  const [subType, setSubType] = useState("");
  const [subSortBy, setSubSortBy] = useState<"name" | "amount">("name");
  const [subSortDir, setSubSortDir] = useState<"asc" | "desc">("asc");

  // Categorie: filtri client-side
  const [catSearch, setCatSearch] = useState("");
  const [catSortBy, setCatSortBy] = useState<"name" | "budget">("name");
  const [catSortDir, setCatSortDir] = useState<"asc" | "desc">("asc");

  // Trasferimenti: filtri data (server-side) + ricerca/conto/sort (client-side)
  const [transStart, setTransStart] = useState(monthStartIso());
  const [transEnd, setTransEnd] = useState(todayIso());
  const [transSearch, setTransSearch] = useState("");
  const [transAccId, setTransAccId] = useState("");
  const [transSortBy, setTransSortBy] = useState<"date" | "name" | "amount">("date");
  const [transSortDir, setTransSortDir] = useState<"asc" | "desc">("desc");

  // Loading
  const [loading, setLoading] = useState<Record<string, boolean>>({});

  // Dialog
  const [dialog, setDialog] = useState<{
    open: boolean; mode: DialogMode; entity: EntityType; data: Record<string, string | number | null>;
  }>({ open: false, mode: "add", entity: "account", data: {} });

  // Snackbar
  const { snack, showSuccess, showError, close: closeSnack } = useSnackbar();

  // Menu di modifica rapida categoria (click sul chip in tabella spese)
  const [catMenu, setCatMenu] = useState<{ anchorEl: HTMLElement; expenseId: number } | null>(null);

  // Suggerimenti budget (calcolati on-demand, non persistiti)
  const [suggestions, setSuggestions] = useState<Record<string, number>>({});
  const [dismissed, setDismissed] = useState<Set<string>>(new Set());
  const [loadingSuggestions, setLoadingSuggestions] = useState(false);
  const [generalBudgetInput, setGeneralBudgetInput] = useState("");
  const [savingGeneralBudget, setSavingGeneralBudget] = useState(false);

  // Banner setup post-onboarding
  const [setupBannerDismissed, setSetupBannerDismissed] = useState(false);
  const missingAccounts = !loading.accounts && accounts.length === 0;
  const missingBudgets = !loading.categories && categories.length > 0 && categories.every(c => c.monthly_budget == null);
  const showSetupBanner = !setupBannerDismissed && (missingAccounts || missingBudgets);
  const monthlyBudgetGuidance = useMemo(() => buildMonthlyBudgetGuidance(categories), [categories]);

  // ---------------------------------------------------------------------------
  // Fetch
  // ---------------------------------------------------------------------------

  const fetchAccounts = useCallback(async () => {
    setLoading(l => ({ ...l, accounts: true }));
    try {
      const json = await apiFetch<{ accounts: Account[] }>("/api/space/accounts");
      setAccounts(json.accounts ?? []);
    } catch {
      // Elenco best-effort: nessun errore mostrato all'utente se la chiamata fallisce.
    } finally {
      setLoading(l => ({ ...l, accounts: false }));
    }
  }, []);

  const fetchCategories = useCallback(async () => {
    setLoading(l => ({ ...l, categories: true }));
    try {
      const json = await apiFetch<{ categories: Category[] }>("/api/space/categories");
      setCategories(json.categories ?? []);
    } catch {
      // Elenco best-effort: nessun errore mostrato all'utente se la chiamata fallisce.
    } finally {
      setLoading(l => ({ ...l, categories: false }));
    }
  }, []);

  const fetchSuggestions = useCallback(async () => {
    setLoadingSuggestions(true);
    try {
      const json = await apiFetch<{ suggestions: Record<string, number> }>("/api/space/categories/suggestions");
      setSuggestions(json.suggestions ?? {});
    } catch {
      // Suggerimenti best-effort: nessun errore mostrato all'utente se la chiamata fallisce.
    } finally {
      setLoadingSuggestions(false);
    }
  }, []);

  const fetchPreferences = useCallback(async () => {
    setLoading(l => ({ ...l, preferences: true }));
    try {
      const json = await apiFetch<UserPreferencesResponse>("/api/user/preferences");
      const parsedBudget = json.monthly_budget == null ? null : Number(json.monthly_budget);
      const monthlyBudget = parsedBudget == null || Number.isFinite(parsedBudget) ? parsedBudget : null;
      setGeneralBudgetInput(monthlyBudget == null ? "" : String(monthlyBudget));
    } catch {
      // Preferenze best-effort: nessun errore mostrato all'utente se la chiamata fallisce.
    } finally {
      setLoading(l => ({ ...l, preferences: false }));
    }
  }, []);

  const fetchSubscriptions = useCallback(async () => {
    setLoading(l => ({ ...l, subscriptions: true }));
    try {
      const json = await apiFetch<{ subscriptions: Subscription[] }>("/api/space/subscriptions");
      setSubscriptions(json.subscriptions ?? []);
    } catch {
      // Elenco best-effort: nessun errore mostrato all'utente se la chiamata fallisce.
    } finally {
      setLoading(l => ({ ...l, subscriptions: false }));
    }
  }, []);

  const fetchIncomeCategories = useCallback(async () => {
    setLoading(l => ({ ...l, incomeCategories: true }));
    try {
      const json = await apiFetch<{ income_categories: IncomeCategoryDto[] }>("/api/income-categories");
      setIncomeCategories(json.income_categories ?? []);
    } catch {
      // Categorie entrate best-effort: nessun errore mostrato all'utente se la chiamata fallisce.
    } finally {
      setLoading(l => ({ ...l, incomeCategories: false }));
    }
  }, []);

  const fetchExpenses = useCallback(async (
    page = expPage, rpp = expRowsPP, start = expStart, end = expEnd,
    search = expSearch, catId = expCatId, accId = expAccId,
    sortBy = expSortBy, sortDir = expSortDir,
  ) => {
    setLoading(l => ({ ...l, expenses: true }));
    try {
      const params: Record<string, string> = { limit: String(rpp), offset: String(page * rpp), start, end };
      if (search) params.search = search;
      if (catId) params.category_id = catId;
      if (accId) params.account_id = accId;
      params.sort_by = sortBy;
      params.sort_dir = sortDir;
      const json = await apiFetch<{ expenses: Expense[]; total: number }>("/api/space/expenses", { params });
      setExpenses(json.expenses ?? []);
      setExpTotal(json.total ?? 0);
    } catch {
      // Elenco best-effort: nessun errore mostrato all'utente se la chiamata fallisce.
    } finally {
      setLoading(l => ({ ...l, expenses: false }));
    }
  }, [expPage, expRowsPP, expStart, expEnd, expSearch, expCatId, expAccId, expSortBy, expSortDir]);

  const fetchIncomes = useCallback(async (
    page = incPage, rpp = incRowsPP, start = incStart, end = incEnd,
    search = incSearch, categoryId = incCategoryId, accId = incAccId,
    sortBy = incSortBy, sortDir = incSortDir,
  ) => {
    setLoading(l => ({ ...l, incomes: true }));
    try {
      const params: Record<string, string> = { limit: String(rpp), offset: String(page * rpp), start, end };
      if (search) params.search = search;
      if (categoryId) params.income_category_id = categoryId;
      if (accId) params.account_id = accId;
      params.sort_by = sortBy;
      params.sort_dir = sortDir;
      const json = await apiFetch<{ incomes: Income[]; total: number }>("/api/space/incomes", { params });
      setIncomes(json.incomes ?? []);
      setIncTotal(json.total ?? 0);
    } catch {
      // Elenco best-effort: nessun errore mostrato all'utente se la chiamata fallisce.
    } finally {
      setLoading(l => ({ ...l, incomes: false }));
    }
  }, [incPage, incRowsPP, incStart, incEnd, incSearch, incCategoryId, incAccId, incSortBy, incSortDir]);

  const fetchTransfers = useCallback(async (start = transStart, end = transEnd) => {
    setLoading(l => ({ ...l, transfers: true }));
    try {
      const json = await apiFetch<{ transfers: Transfer[] }>("/api/space/transfers", { params: { start, end } });
      setTransfers(json.transfers ?? []);
    } catch {
      // Elenco best-effort: nessun errore mostrato all'utente se la chiamata fallisce.
    } finally {
      setLoading(l => ({ ...l, transfers: false }));
    }
  }, [transStart, transEnd]);

  // Carica tutto al mount e poi su cambio tab
  useEffect(() => { fetchAccounts(); fetchCategories(); fetchSubscriptions(); fetchIncomeCategories(); fetchSuggestions(); fetchPreferences(); }, [fetchAccounts, fetchCategories, fetchSubscriptions, fetchIncomeCategories, fetchSuggestions, fetchPreferences]);
  useEffect(() => { if (tab === 1) fetchSuggestions(); }, [tab, fetchSuggestions]);
  useEffect(() => { if (tab === 3) fetchExpenses(); }, [tab, fetchExpenses]);
  useEffect(() => { if (tab === 4) fetchIncomes(); }, [tab, fetchIncomes]);
  useEffect(() => { if (tab === 5) fetchTransfers(); }, [tab, fetchTransfers]);

  // ---------------------------------------------------------------------------
  // Dialog helpers
  // ---------------------------------------------------------------------------

  function openAdd(entity: EntityType) {
    const defaults: Record<EntityType, Record<string, string | number | null>> = {
      account: { name: "", account_type: "", initial_balance: 0 },
      category: { name: "", monthly_budget: "", description: "" },
      subscription: { name: "", amount: "", sub_type: "", last_billed: "", account_id: "", category_id: "" },
      expense: { name: "", amount: "", date: todayIso(), category: "", category_id: "", account_id: "" },
      incomeCategory: { name: "", description: "" },
      income: { name: "", amount: "", date: todayIso(), income_category_id: "", income_category: "", account_id: "" },
      transfer: { name: "", amount: "", date: todayIso(), from_account_id: "", to_account_id: "" },
    };
    setDialog({ open: true, mode: "add", entity, data: defaults[entity] });
  }

  function openEdit(entity: EntityType, row: Record<string, string | number | null>) {
    setDialog({ open: true, mode: "edit", entity, data: { ...row } });
  }

  function closeDialog() { setDialog(d => ({ ...d, open: false })); }

  function setField(key: string, value: string | number | null) {
    setDialog(d => ({ ...d, data: { ...d.data, [key]: value } }));
  }

  // ---------------------------------------------------------------------------
  // Save (add or edit)
  // ---------------------------------------------------------------------------

  async function handleSave() {
    const { mode, entity, data } = dialog;
    const path = ENTITY_PATH[entity];
    const collectionUrl = entity === "incomeCategory"
      ? "/api/income-categories"
      : `/api/space/${path}`;
    const url = mode === "add" ? collectionUrl : `${collectionUrl}/${data.id}`;
    const method = mode === "add" ? "POST" : "PUT";

    // Per le spese, risolvi category_id → nome categoria per la POST
    let bodyData = { ...data };
    if (entity === "expense" && mode === "add") {
      const cat = categories.find(c => c.id === Number(data.category_id));
      bodyData = { ...bodyData, category: cat?.name ?? "" };
    }

    try {
      await apiFetch(url, { method, body: bodyData });
      closeDialog();
      showSuccess(mode === "add" ? "Aggiunto con successo" : "Aggiornato con successo");
      refreshEntity(entity);
    } catch (e: unknown) {
      showError(apiErrorMessage(e, "Errore sconosciuto"));
    }
  }

  async function saveGeneralMonthlyBudget() {
    const validation = validateGeneralMonthlyBudget(
      generalBudgetInput,
      monthlyBudgetGuidance.categoryBudgetTotal,
    );
    if (!validation.ok) {
      showError(validation.error);
      return;
    }

    setSavingGeneralBudget(true);
    try {
      await apiFetch("/api/user/preferences", { method: "PUT", body: { monthly_budget: validation.value } });
      setGeneralBudgetInput(validation.value == null ? "" : String(validation.value));
      showSuccess("Budget mensile generale aggiornato");
    } catch (e: unknown) {
      showError(apiErrorMessage(e, "Errore sconosciuto"));
    } finally {
      setSavingGeneralBudget(false);
    }
  }

  // ---------------------------------------------------------------------------
  // Modifica rapida categoria (click sul chip in tabella spese)
  // ---------------------------------------------------------------------------

  async function quickUpdateCategory(expenseId: number, category: Category) {
    setCatMenu(null);
    try {
      await apiFetch(`/api/space/expenses/${expenseId}`, { method: "PUT", body: { category_id: category.id } });
      setExpenses(prev => prev.map(e =>
        e.id === expenseId ? { ...e, category_id: category.id, category: category.name } : e
      ));
      showSuccess("Categoria aggiornata");
    } catch (e: unknown) {
      showError(apiErrorMessage(e, "Errore sconosciuto"));
    }
  }

  // ---------------------------------------------------------------------------
  // Delete
  // ---------------------------------------------------------------------------

  async function handleDelete(entity: EntityType, id: number) {
    const collectionUrl = entity === "incomeCategory"
      ? "/api/income-categories"
      : `/api/space/${ENTITY_PATH[entity]}`;
    try {
      await apiFetch(`${collectionUrl}/${id}`, { method: "DELETE" });
      showSuccess("Eliminato");
      refreshEntity(entity);
    } catch (e: unknown) {
      showError(apiErrorMessage(e, "Errore sconosciuto"));
    }
  }

  function refreshEntity(entity: EntityType) {
    if (entity === "account") fetchAccounts();
    else if (entity === "category") fetchCategories();
    else if (entity === "incomeCategory") fetchIncomeCategories();
    else if (entity === "subscription") fetchSubscriptions();
    else if (entity === "expense") fetchExpenses();
    else if (entity === "income") fetchIncomes();
    else if (entity === "transfer") { fetchTransfers(); fetchAccounts(); }
  }

  // ---------------------------------------------------------------------------
  // Suggerimenti budget
  // ---------------------------------------------------------------------------

  async function acceptSuggestion(cat: Category, suggested: number) {
    try {
      await apiFetch(`/api/space/categories/${cat.id}/accept-suggestion`, {
        method: "POST",
        body: { suggested_budget: suggested },
      });
      // Dismetti subito così non ricompare dopo il ricalcolo
      setDismissed(prev => new Set(prev).add(cat.name));
      showSuccess(`Budget ${cat.name} aggiornato a ${fmtCurrency(suggested)}`);
      await fetchCategories();
    } catch (e: unknown) {
      showError(apiErrorMessage(e, "Errore"));
    }
  }

  function dismissSuggestion(catName: string) {
    setDismissed(prev => new Set(prev).add(catName));
  }

  async function acceptAllSuggestions() {
    const toAccept = Object.entries(suggestions).filter(([name, suggested]) => {
      if (dismissed.has(name)) return false;
      const cat = categories.find(c => c.name === name);
      return isSuggestionRelevant(cat?.monthly_budget ?? null, suggested);
    });
    for (const [name, amount] of toAccept) {
      const cat = categories.find(c => c.name === name);
      if (cat) await acceptSuggestion(cat, amount);
    }
  }

  // Un consiglio budget si mostra solo se non c'è ancora un budget impostato, oppure
  // se differisce di più del 5% da quello attuale: sotto quella soglia il consiglio
  // non aggiunge informazione utile e sarebbe solo rumore in lista.
  function isSuggestionRelevant(currentBudget: number | null, suggested: number): boolean {
    if (!currentBudget) return true;
    return Math.abs((suggested - currentBudget) / currentBudget) > 0.05;
  }

  // ---------------------------------------------------------------------------
  // Liste derivate (client-side filter + sort)
  // ---------------------------------------------------------------------------

  const filteredSubs = useMemo(() => {
    const q = subSearch.toLowerCase();
    let r = subscriptions
      .filter(s => s.name.toLowerCase().includes(q))
      .filter(s => !subType || s.sub_type === subType);
    r = [...r].sort((a, b) => {
      const v = subSortBy === "amount"
        ? (a.amount ?? 0) - (b.amount ?? 0)
        : a.name.localeCompare(b.name, "it");
      return subSortDir === "asc" ? v : -v;
    });
    return r;
  }, [subscriptions, subSearch, subType, subSortBy, subSortDir]);

  const filteredCats = useMemo(() => {
    const q = catSearch.toLowerCase();
    let r = categories.filter(c => c.name.toLowerCase().includes(q));
    r = [...r].sort((a, b) => {
      const v = catSortBy === "budget"
        ? (a.monthly_budget ?? 0) - (b.monthly_budget ?? 0)
        : a.name.localeCompare(b.name, "it");
      return catSortDir === "asc" ? v : -v;
    });
    return r;
  }, [categories, catSearch, catSortBy, catSortDir]);

  const filteredTransfers = useMemo(() => {
    const q = transSearch.toLowerCase();
    const accId = transAccId ? Number(transAccId) : null;
    let r = transfers
      .filter(t => t.name.toLowerCase().includes(q))
      .filter(t => !accId || t.from_account_id === accId || t.to_account_id === accId);
    r = [...r].sort((a, b) => {
      const v = transSortBy === "amount"
        ? (a.amount ?? 0) - (b.amount ?? 0)
        : transSortBy === "date"
          ? a.date.localeCompare(b.date)
          : a.name.localeCompare(b.name, "it");
      return transSortDir === "asc" ? v : -v;
    });
    return r;
  }, [transfers, transSearch, transAccId, transSortBy, transSortDir]);

  // ---------------------------------------------------------------------------
  // Render tabelle
  // ---------------------------------------------------------------------------

  function renderAccounts() {
    const columns: Column<Account>[] = [
      { key: "name", header: "Nome", render: row => row.name },
      {
        key: "account_type", header: "Tipo",
        render: row => row.account_type
          ? <Chip label={row.account_type} size="small" sx={{ fontSize: "0.7rem" }} />
          : <span style={{ color: MUTED }}>—</span>,
      },
      {
        key: "current_balance", header: "Saldo", align: "right",
        render: row => (
          <span style={{ fontWeight: 600, color: row.current_balance >= 0 ? PRIMARY : ACCENT }}>
            {fmtSignedCurrency(row.current_balance)}
          </span>
        ),
      },
    ];
    return (
      <Box data-tour="spazio-conti">
        <TabToolbar label="Conti" onAdd={() => openAdd("account")} loading={loading.accounts} />
        <ResponsiveDataTable
          ariaLabel="Elenco conti"
          columns={columns}
          rows={accounts}
          rowKey={row => row.id}
          loading={loading.accounts}
          minWidth={500}
          mobilePrimary={row => row.name}
          mobileSecondary={row => row.account_type ?? undefined}
          mobileAmount={row => (
            <span style={{ color: row.current_balance >= 0 ? PRIMARY : ACCENT }}>
              {fmtSignedCurrency(row.current_balance)}
            </span>
          )}
          actions={row => (
            <RowActions
              onEdit={() => openEdit("account", {
                id: row.id, name: row.name, account_type: row.account_type ?? "",
                balance: row.opening_balance,
              })}
              onDelete={() => handleDelete("account", row.id)}
            />
          )}
        />
      </Box>
    );
  }

  function renderExpenseCategories() {
    const activeSuggestions = Object.entries(suggestions).filter(([name, suggested]) => {
      if (dismissed.has(name)) return false;
      const cat = categories.find(c => c.name === name);
      return isSuggestionRelevant(cat?.monthly_budget ?? null, suggested);
    });
    const hasSuggestions = activeSuggestions.length > 0;

    function handleCatSort(field: string) {
      const newDir = catSortBy === field ? (catSortDir === "asc" ? "desc" : "asc") : "asc";
      setCatSortBy(field as "name" | "budget");
      setCatSortDir(newDir as "asc" | "desc");
    }

    return (
      <Box data-tour="spazio-categorie">
        <TabToolbar label="Categorie di spesa" onAdd={() => openAdd("category")} loading={loading.categories || loadingSuggestions}>
          <SearchInput value={catSearch} onChange={setCatSearch} placeholder="Cerca categoria..." />
        </TabToolbar>

        <Box sx={{
          display: "flex", flexDirection: { xs: "column", sm: "row" }, gap: 1,
          alignItems: { xs: "stretch", sm: "flex-end" },
          px: 2, py: 1.5, borderBottom: `1px solid ${BORDER}`,
        }}>
          <TextField
            label="Budget mensile generale (€)"
            type="number"
            value={generalBudgetInput}
            onChange={e => setGeneralBudgetInput(e.target.value)}
            helperText={monthlyBudgetGuidance.hasCategoryBudgets
              ? `Minimo: ${fmtCurrency(monthlyBudgetGuidance.categoryBudgetTotal)}`
              : "Facoltativo: puoi lasciarlo vuoto."}
            fullWidth
            sx={{ maxWidth: { sm: 280 } }}
            slotProps={{
              input: {
                endAdornment: (
                  <InfoButton
                    label="Come funziona il budget mensile generale"
                    explanation={monthlyBudgetGuidance.suggestedBudget == null
                      ? "Imposta il limite complessivo del mese quando hai abbastanza storico per sceglierlo. Puoi anche lasciarlo vuoto: in quel caso Expensum usa la somma dei budget di categoria come riferimento."
                      : `Imposta il limite complessivo del mese quando hai abbastanza storico per sceglierlo. Consiglio Expensum: almeno ${fmtCurrency(monthlyBudgetGuidance.suggestedBudget)}, pari alla somma dei budget categoria.`}
                  />
                ),
              },
            }}
          />
          <Button
            variant="contained"
            disableElevation
            disabled={savingGeneralBudget}
            onClick={saveGeneralMonthlyBudget}
            sx={{ minHeight: 40, flexShrink: 0, bgcolor: PRIMARY, color: "primary.contrastText", "&:hover": { bgcolor: "#4AA7AE" } }}
          >
            Salva
          </Button>
        </Box>

        {hasSuggestions && (
          <Alert
            severity="info"
            sx={{ mb: 2, borderRadius: 2 }}
            action={
              <Button
                size="small"
                variant="contained"
                disableElevation
                sx={{ bgcolor: PRIMARY, color: "primary.contrastText", fontSize: "0.75rem", whiteSpace: "nowrap",
                      "&:hover": { bgcolor: "#4AA7AE" } }}
                onClick={acceptAllSuggestions}
              >
                Accetta tutti
              </Button>
            }
          >
            Ho <strong>{activeSuggestions.length}</strong> consigli budget basati sulle tue spese recenti.
          </Alert>
        )}

        <ResponsiveDataTable
          ariaLabel="Elenco categorie"
          minWidth={hasSuggestions ? 620 : 400}
          columns={buildCategoryColumns(hasSuggestions)}
          rows={filteredCats}
          rowKey={row => row.id}
          loading={loading.categories}
          sortBy={catSortBy}
          sortDir={catSortDir}
          onSort={field => handleCatSort(field)}
          mobilePrimary={row => row.name}
          mobileSecondary={row => {
            const suggested = suggestions[row.name];
            const showSuggestion = suggested != null && !dismissed.has(row.name) && isSuggestionRelevant(row.monthly_budget, suggested);
            return showSuggestion ? `Consiglio: ${fmtCurrency(suggested)}` : undefined;
          }}
          mobileAmount={row => (
            <span style={{ color: PRIMARY }}>
              {row.monthly_budget != null ? fmtCurrency(row.monthly_budget) : <span style={{ color: MUTED }}>—</span>}
            </span>
          )}
          actions={row => {
            const suggested = suggestions[row.name];
            const showSuggestion = suggested != null && !dismissed.has(row.name) && isSuggestionRelevant(row.monthly_budget, suggested);
            return (
              <Box sx={{ display: "flex", alignItems: "center", gap: 0.5 }}>
                {showSuggestion && (
                  <>
                    <Tooltip title="Accetta consiglio budget">
                      <IconButton aria-label="Accetta consiglio budget" sx={{ width: 44, height: 44, color: "success.main" }} onClick={() => acceptSuggestion(row, suggested)}>
                        <Check size={14} />
                      </IconButton>
                    </Tooltip>
                    <Tooltip title="Scarta consiglio budget">
                      <IconButton aria-label="Scarta consiglio budget" sx={{ width: 44, height: 44, color: MUTED }} onClick={() => dismissSuggestion(row.name)}>
                        <X size={14} />
                      </IconButton>
                    </Tooltip>
                  </>
                )}
                <RowActions
                  onEdit={() => openEdit("category", { id: row.id, name: row.name, monthly_budget: row.monthly_budget ?? "", description: row.description ?? "" })}
                  onDelete={() => handleDelete("category", row.id)}
                  editTourAttr={filteredCats[0]?.id === row.id ? "category-edit-button" : undefined}
                />
              </Box>
            );
          }}
        />
      </Box>
    );
  }

  function renderIncomeCategories() {
    return (
      <Box>
        <TabToolbar
          label="Categorie di entrata"
          onAdd={() => openAdd("incomeCategory")}
          loading={loading.incomeCategories}
        />
        <ResponsiveDataTable
          ariaLabel="Elenco categorie entrata"
          minWidth={360}
          columns={[
            { key: "name", header: "Nome", render: row => row.name },
            { key: "description", header: "Descrizione", render: row => row.description || "—" },
          ]}
          rows={incomeCategories}
          rowKey={row => row.id}
          loading={loading.incomeCategories}
          mobilePrimary={row => row.name}
          mobileSecondary={row => row.description || undefined}
          actions={row => (
            <RowActions
              onEdit={() => openEdit("incomeCategory", {
                id: row.id, name: row.name, description: row.description ?? "",
              })}
              onDelete={() => handleDelete("incomeCategory", row.id)}
            />
          )}
        />
      </Box>
    );
  }

  function renderCategories() {
    return (
      <Box data-tour="spazio-categorie">
        <Box sx={{ px: 2, pt: 2, pb: 1.5, borderBottom: `1px solid ${BORDER}` }}>
          <Typography variant="h6" sx={{ fontWeight: 600, fontSize: "1rem", mb: 0.25 }}>
            Categorie
          </Typography>
          <Typography variant="body2" color="text.secondary" sx={{ mb: 1.25 }}>
            Scegli se gestire le categorie per le spese o per le entrate.
          </Typography>
          <ToggleButtonGroup
            value={categoryKind}
            exclusive
            onChange={(_, kind) => kind && setCategoryKind(kind)}
            aria-label="Tipo di categorie"
            fullWidth
            size="small"
            sx={{ "& .MuiToggleButton-root": { minHeight: 44, textTransform: "none", fontWeight: 600 } }}
          >
            <ToggleButton value="expense">Spese</ToggleButton>
            <ToggleButton value="income">Entrate</ToggleButton>
          </ToggleButtonGroup>
        </Box>
        {categoryKind === "expense" ? renderExpenseCategories() : renderIncomeCategories()}
      </Box>
    );
  }

  function buildCategoryColumns(hasSuggestions: boolean): Column<Category>[] {
    const columns: Column<Category>[] = [
      { key: "name", header: "Nome", sortable: true, render: row => row.name },
      {
        key: "budget", header: "Budget mensile", align: "right", sortable: true,
        render: row => (
          <span style={{ color: PRIMARY }}>
            {row.monthly_budget != null ? fmtCurrency(row.monthly_budget) : <span style={{ color: MUTED }}>—</span>}
          </span>
        ),
      },
    ];
    if (hasSuggestions) {
      columns.push({
        key: "suggestion", header: "Consiglio", align: "right", hideOnMobileCard: true,
        render: row => {
          const suggested = suggestions[row.name];
          const showSuggestion = suggested != null && !dismissed.has(row.name) && isSuggestionRelevant(row.monthly_budget, suggested);
          if (!showSuggestion) return null;
          const delta = row.monthly_budget != null ? (suggested - row.monthly_budget) / row.monthly_budget : null;
          const trendIcon = delta == null ? "" : delta > 0.05 ? " ↑" : delta < -0.05 ? " ↓" : " ≈";
          return (
            <Typography component="span" variant="caption" sx={{ color: "primary.main", fontWeight: 600 }}>
              {fmtCurrency(suggested)}{trendIcon}
            </Typography>
          );
        },
      });
    }
    return columns;
  }

  function renderSubscriptions() {
    function handleSubSort(field: string) {
      const newDir = subSortBy === field ? (subSortDir === "asc" ? "desc" : "asc") : "asc";
      setSubSortBy(field as "name" | "amount");
      setSubSortDir(newDir as "asc" | "desc");
    }

    return (
      <>
        <TabToolbar label="Abbonamenti" onAdd={() => openAdd("subscription")} loading={loading.subscriptions}>
          <SearchInput value={subSearch} onChange={setSubSearch} placeholder="Cerca abbonamento..." />
          <FilterSelect
            label="Frequenza"
            value={subType}
            onChange={setSubType}
            options={SUB_TYPES.map(t => ({ value: t, label: t }))}
          />
        </TabToolbar>
        <ResponsiveDataTable
          ariaLabel="Elenco abbonamenti"
          minWidth={700}
          columns={subscriptionColumns}
          rows={filteredSubs}
          rowKey={row => row.id}
          loading={loading.subscriptions}
          sortBy={subSortBy}
          sortDir={subSortDir}
          onSort={field => handleSubSort(field)}
          mobilePrimary={row => row.name}
          mobileSecondary={row => [row.sub_type, row.account_name || null].filter(Boolean).join(" · ") || undefined}
          mobileAmount={row => (
            <span style={{ color: ACCENT }}>
              {row.amount != null ? fmtCurrency(row.amount) : <span style={{ color: MUTED }}>—</span>}
            </span>
          )}
          actions={row => (
            <RowActions
              onEdit={() => openEdit("subscription", {
                id: row.id, name: row.name,
                amount: row.amount ?? "", sub_type: row.sub_type ?? "",
                last_billed: row.last_billed ?? "", account_id: row.account_id ?? "",
                category_id: row.category_id ?? "",
              })}
              onDelete={() => handleDelete("subscription", row.id)}
            />
          )}
        />
      </>
    );
  }

  const subscriptionColumns: Column<Subscription>[] = [
    { key: "name", header: "Nome", sortable: true, render: row => row.name },
    {
      key: "amount", header: "Importo", align: "right", sortable: true,
      render: row => (
        <span style={{ color: ACCENT, fontWeight: 600 }}>
          {row.amount != null ? fmtCurrency(row.amount) : <span style={{ color: MUTED }}>—</span>}
        </span>
      ),
    },
    {
      key: "sub_type", header: "Frequenza", hideOnMobileCard: true,
      render: row => row.sub_type
        ? <Chip label={row.sub_type} size="small" sx={{ fontSize: "0.7rem", textTransform: "capitalize" }} />
        : <span style={{ color: MUTED }}>—</span>,
    },
    { key: "last_billed", header: "Ultima fattura", hideOnMobileCard: true, render: row => <span style={{ color: MUTED }}>{formatDateIt(row.last_billed)}</span> },
    { key: "account_name", header: "Conto", hideOnMobileCard: true, render: row => <span style={{ color: MUTED }}>{row.account_name || "—"}</span> },
  ];

  function renderExpenses() {
    function onExpSearch(v: string) { setExpSearch(v); setExpPage(0); fetchExpenses(0, expRowsPP, expStart, expEnd, v, expCatId, expAccId, expSortBy, expSortDir); }
    function onExpCat(v: string) { setExpCatId(v); setExpPage(0); fetchExpenses(0, expRowsPP, expStart, expEnd, expSearch, v, expAccId, expSortBy, expSortDir); }
    function onExpAcc(v: string) { setExpAccId(v); setExpPage(0); fetchExpenses(0, expRowsPP, expStart, expEnd, expSearch, expCatId, v, expSortBy, expSortDir); }
    function handleExpSort(field: string) {
      const newDir: "asc" | "desc" = expSortBy === field ? (expSortDir === "asc" ? "desc" : "asc") : "asc";
      setExpSortBy(field); setExpSortDir(newDir); setExpPage(0);
      fetchExpenses(0, expRowsPP, expStart, expEnd, expSearch, expCatId, expAccId, field, newDir);
    }
    function renderExpenseCategoryChip(row: Expense) {
      return row.category
        ? (
          <Chip
            label={row.category}
            size="small"
            clickable
            onClick={e => setCatMenu({ anchorEl: e.currentTarget, expenseId: row.id })}
            sx={{ fontSize: "0.7rem", bgcolor: "rgba(233,241,234,0.06)" }}
          />
        )
        : (
          <Chip
            label="Assegna categoria"
            size="small"
            clickable
            variant="outlined"
            onClick={e => setCatMenu({ anchorEl: e.currentTarget, expenseId: row.id })}
            sx={{ fontSize: "0.7rem", color: MUTED, borderStyle: "dashed" }}
          />
        );
    }

    return (
      <>
        <TabToolbar label="Spese" onAdd={() => openAdd("expense")} loading={loading.expenses}>
          <SearchInput value={expSearch} onChange={onExpSearch} placeholder="Cerca spesa..." />
          <FilterSelect
            label="Categoria"
            value={expCatId}
            onChange={onExpCat}
            options={categories.map(c => ({ value: String(c.id), label: c.name }))}
          />
          <FilterSelect
            label="Conto"
            value={expAccId}
            onChange={onExpAcc}
            options={accounts.map(a => ({ value: String(a.id), label: a.name }))}
          />
          <DateRangeFilter
            start={expStart} end={expEnd}
            onChange={(s, e) => { setExpStart(s); setExpEnd(e); setExpPage(0); fetchExpenses(0, expRowsPP, s, e, expSearch, expCatId, expAccId, expSortBy, expSortDir); }}
          />
        </TabToolbar>
        <ResponsiveDataTable
          ariaLabel="Elenco spese"
          minWidth={700}
          columns={[
            { key: "date", header: "Data", sortable: true, hideOnMobileCard: true, render: row => <span style={{ color: MUTED }}>{formatDateIt(row.date)}</span> },
            { key: "name", header: "Descrizione", sortable: true, render: row => row.name },
            {
              key: "amount", header: "Importo", align: "right", sortable: true,
              render: row => <span style={{ color: ACCENT, fontWeight: 600 }}>{fmtCurrency(row.amount)}</span>,
            },
            { key: "category", header: "Categoria", render: row => renderExpenseCategoryChip(row) },
            { key: "account", header: "Conto", hideOnMobileCard: true, render: row => <span style={{ color: MUTED }}>{row.account || "—"}</span> },
          ]}
          rows={expenses}
          rowKey={row => row.id}
          loading={loading.expenses}
          sortBy={expSortBy}
          sortDir={expSortDir}
          onSort={handleExpSort}
          mobilePrimary={row => row.name}
          mobileSecondary={row => (
            <Box sx={{ display: "flex", alignItems: "center", gap: 0.75, flexWrap: "wrap" }}>
              <span>{formatDateIt(row.date)}</span>
              {renderExpenseCategoryChip(row)}
              {row.account && <span>{row.account}</span>}
            </Box>
          )}
          mobileAmount={row => <span style={{ color: ACCENT }}>{fmtCurrency(row.amount)}</span>}
          actions={row => (
            <RowActions
              onEdit={() => openEdit("expense", {
                id: row.id, name: row.name, amount: row.amount,
                date: row.date, category_id: row.category_id ?? "",
                account_id: row.account_id ?? "",
              })}
              onDelete={() => handleDelete("expense", row.id)}
            />
          )}
        />
        <TablePagination
          component="div"
          count={expTotal}
          page={expPage}
          rowsPerPage={expRowsPP}
          rowsPerPageOptions={[10, 25, 50]}
          onPageChange={(_, p) => { setExpPage(p); fetchExpenses(p, expRowsPP, expStart, expEnd, expSearch, expCatId, expAccId, expSortBy, expSortDir); }}
          onRowsPerPageChange={e => { const rpp = parseInt(e.target.value); setExpRowsPP(rpp); setExpPage(0); fetchExpenses(0, rpp, expStart, expEnd, expSearch, expCatId, expAccId, expSortBy, expSortDir); }}
          labelRowsPerPage="Righe:"
          sx={{ fontSize: "0.75rem" }}
        />
        <Menu
          anchorEl={catMenu?.anchorEl ?? null}
          open={!!catMenu}
          onClose={() => setCatMenu(null)}
        >
          {categories.map(c => (
            <MenuItem key={c.id} onClick={() => catMenu && quickUpdateCategory(catMenu.expenseId, c)}>
              {c.name}
            </MenuItem>
          ))}
          {categories.length === 0 && <MenuItem disabled>Nessuna categoria disponibile</MenuItem>}
        </Menu>
      </>
    );
  }

  function renderIncomes() {
    const activeCategories = activeIncomeCategories(incomeCategories);
    function onIncSearch(v: string) { setIncSearch(v); setIncPage(0); fetchIncomes(0, incRowsPP, incStart, incEnd, v, incCategoryId, incAccId, incSortBy, incSortDir); }
    function onIncCategory(v: string) { setIncCategoryId(v); setIncPage(0); fetchIncomes(0, incRowsPP, incStart, incEnd, incSearch, v, incAccId, incSortBy, incSortDir); }
    function onIncAcc(v: string) { setIncAccId(v); setIncPage(0); fetchIncomes(0, incRowsPP, incStart, incEnd, incSearch, incCategoryId, v, incSortBy, incSortDir); }
    function handleIncSort(field: string) {
      const newDir: "asc" | "desc" = incSortBy === field ? (incSortDir === "asc" ? "desc" : "asc") : "asc";
      setIncSortBy(field); setIncSortDir(newDir); setIncPage(0);
      fetchIncomes(0, incRowsPP, incStart, incEnd, incSearch, incCategoryId, incAccId, field, newDir);
    }

    return (
      <>
        <TabToolbar label="Entrate" onAdd={() => openAdd("income")} loading={loading.incomes}>
          <Button size="small" onClick={() => { setTab(1); setCategoryKind("income"); }} sx={{ minHeight: 44 }}>
            Gestisci categorie
          </Button>
          <SearchInput value={incSearch} onChange={onIncSearch} placeholder="Cerca entrata..." />
          <FilterSelect
            label="Categoria"
            value={incCategoryId}
            onChange={onIncCategory}
            options={activeCategories.map(category => ({ value: String(category.id), label: category.name }))}
          />
          <FilterSelect
            label="Conto"
            value={incAccId}
            onChange={onIncAcc}
            options={accounts.map(a => ({ value: String(a.id), label: a.name }))}
          />
          <DateRangeFilter
            start={incStart} end={incEnd}
            onChange={(s, e) => { setIncStart(s); setIncEnd(e); setIncPage(0); fetchIncomes(0, incRowsPP, s, e, incSearch, incCategoryId, incAccId, incSortBy, incSortDir); }}
          />
        </TabToolbar>
        <ResponsiveDataTable
          ariaLabel="Elenco entrate"
          minWidth={700}
          columns={[
            { key: "date", header: "Data", sortable: true, hideOnMobileCard: true, render: row => <span style={{ color: MUTED }}>{formatDateIt(row.date)}</span> },
            { key: "name", header: "Descrizione", sortable: true, render: row => row.name },
            {
              key: "amount", header: "Importo", align: "right", sortable: true,
              render: row => <span style={{ color: INCOME_COLOR, fontWeight: 600 }}>{fmtCurrency(row.amount)}</span>,
            },
            {
              key: "income_category", header: "Categoria",
              render: row => incomeCategoryLabel(row)
                ? <Chip label={incomeCategoryLabel(row)} size="small" sx={{ fontSize: "0.7rem", bgcolor: "var(--color-primary-light)", color: PRIMARY, textTransform: "capitalize" }} />
                : <span style={{ color: MUTED }}>—</span>,
            },
            { key: "account", header: "Conto", hideOnMobileCard: true, render: row => <span style={{ color: MUTED }}>{row.account || "—"}</span> },
          ]}
          rows={incomes}
          rowKey={row => row.id}
          loading={loading.incomes}
          sortBy={incSortBy}
          sortDir={incSortDir}
          onSort={handleIncSort}
          mobilePrimary={row => row.name}
          mobileSecondary={row => (
            <Box sx={{ display: "flex", alignItems: "center", gap: 0.75, flexWrap: "wrap" }}>
              <span>{formatDateIt(row.date)}</span>
              {incomeCategoryLabel(row) && <Chip label={incomeCategoryLabel(row)} size="small" sx={{ fontSize: "0.7rem", bgcolor: "var(--color-primary-light)", color: PRIMARY, textTransform: "capitalize" }} />}
              {row.account && <span>{row.account}</span>}
            </Box>
          )}
          mobileAmount={row => <span style={{ color: INCOME_COLOR }}>{fmtCurrency(row.amount)}</span>}
          actions={row => (
            <RowActions
              onEdit={() => openEdit("income", {
                id: row.id, name: row.name, amount: row.amount,
                date: row.date, income_category_id: row.income_category_id ?? "",
                income_category: incomeCategoryLabel(row),
                account_id: row.account_id ?? "",
              })}
              onDelete={() => handleDelete("income", row.id)}
            />
          )}
        />
        <TablePagination
          component="div"
          count={incTotal}
          page={incPage}
          rowsPerPage={incRowsPP}
          rowsPerPageOptions={[10, 25, 50]}
          onPageChange={(_, p) => { setIncPage(p); fetchIncomes(p, incRowsPP, incStart, incEnd, incSearch, incCategoryId, incAccId, incSortBy, incSortDir); }}
          onRowsPerPageChange={e => { const rpp = parseInt(e.target.value); setIncRowsPP(rpp); setIncPage(0); fetchIncomes(0, rpp, incStart, incEnd, incSearch, incCategoryId, incAccId, incSortBy, incSortDir); }}
          labelRowsPerPage="Righe:"
          sx={{ fontSize: "0.75rem" }}
        />
      </>
    );
  }

  function renderTransfers() {
    const accName = (id: number) => accounts.find(a => a.id === id)?.name ?? "—";
    function handleTransSort(field: string) {
      const f = field as "date" | "name" | "amount";
      const newDir: "asc" | "desc" = transSortBy === f ? (transSortDir === "asc" ? "desc" : "asc") : "asc";
      setTransSortBy(f); setTransSortDir(newDir);
    }
    return (
      <Box>
        <TabToolbar label="Trasferimenti" onAdd={() => openAdd("transfer")} loading={loading.transfers}>
          <SearchInput value={transSearch} onChange={setTransSearch} placeholder="Cerca trasferimento..." />
          <FilterSelect
            label="Conto"
            value={transAccId}
            onChange={setTransAccId}
            options={accounts.map(a => ({ value: String(a.id), label: a.name }))}
          />
          <DateRangeFilter
            start={transStart} end={transEnd}
            onChange={(s, e) => { setTransStart(s); setTransEnd(e); fetchTransfers(s, e); }}
          />
          {accounts.length < 2 && (
            <Typography variant="caption" color="text.secondary">
              Servono almeno due conti per creare un trasferimento
            </Typography>
          )}
        </TabToolbar>
        <ResponsiveDataTable
          ariaLabel="Elenco trasferimenti"
          minWidth={600}
          columns={[
            { key: "date", header: "Data", sortable: true, hideOnMobileCard: true, render: row => <span style={{ color: MUTED }}>{formatDateIt(row.date)}</span> },
            { key: "name", header: "Descrizione", sortable: true, render: row => row.name },
            { key: "from", header: "Da", hideOnMobileCard: true, render: row => <span style={{ color: MUTED }}>{accName(row.from_account_id)}</span> },
            { key: "to", header: "A", hideOnMobileCard: true, render: row => <span style={{ color: MUTED }}>{accName(row.to_account_id)}</span> },
            {
              key: "amount", header: "Importo", align: "right", sortable: true,
              render: row => <span style={{ color: PRIMARY, fontWeight: 600 }}>{fmtCurrency(row.amount)}</span>,
            },
          ]}
          rows={filteredTransfers}
          rowKey={row => row.id}
          loading={loading.transfers}
          sortBy={transSortBy}
          sortDir={transSortDir}
          onSort={handleTransSort}
          mobilePrimary={row => row.name}
          mobileSecondary={row => `${formatDateIt(row.date)} · ${accName(row.from_account_id)} → ${accName(row.to_account_id)}`}
          mobileAmount={row => <span style={{ color: PRIMARY }}>{fmtCurrency(row.amount)}</span>}
          actions={row => (
            <RowActions
              onEdit={() => openEdit("transfer", {
                id: row.id, name: row.name, amount: row.amount,
                date: row.date, from_account_id: row.from_account_id,
                to_account_id: row.to_account_id,
              })}
              onDelete={() => handleDelete("transfer", row.id)}
            />
          )}
        />
      </Box>
    );
  }

  // ---------------------------------------------------------------------------
  // Dialog content per ogni entità
  // ---------------------------------------------------------------------------

  function renderDialogFields() {
    const { entity, data } = dialog;

    if (entity === "account") return (
      <>
        <TextField label="Nome *" fullWidth size="small" margin="dense" value={data.name ?? ""}
          onChange={e => setField("name", e.target.value)} />
        <FormControl fullWidth size="small" margin="dense">
          <InputLabel>Tipo conto</InputLabel>
          <Select label="Tipo conto" value={data.account_type ?? ""}
            onChange={e => setField("account_type", e.target.value)}>
            <MenuItem value=""><em>Nessuno</em></MenuItem>
            {ACCOUNT_TYPES.map(t => <MenuItem key={t} value={t}>{t}</MenuItem>)}
          </Select>
        </FormControl>
        <TextField label="Saldo iniziale (€)" fullWidth size="small" margin="dense" type="number"
          value={data.balance ?? data.initial_balance ?? 0}
          onChange={e => setField(dialog.mode === "edit" ? "balance" : "initial_balance", e.target.value)} />
      </>
    );

    if (entity === "category") return (
      <>
        <TextField label="Nome *" fullWidth size="small" margin="dense" value={data.name ?? ""}
          onChange={e => setField("name", e.target.value)} />
        <TextField label="Budget mensile (€)" fullWidth size="small" margin="dense" type="number"
          value={data.monthly_budget ?? ""}
          onChange={e => setField("monthly_budget", e.target.value)} />
        <TextField label="Descrizione (facoltativa)" fullWidth size="small" margin="dense"
          multiline minRows={2} inputProps={{ maxLength: 500 }}
          placeholder="Es. spese fatte per uscire fuori a cena o pranzo"
          helperText="Aiuta l'assistente a categorizzare meglio le spese ambigue"
          value={data.description ?? ""}
          onChange={e => setField("description", e.target.value)} />
      </>
    );

    if (entity === "incomeCategory") return (
      <>
        <TextField label="Nome *" fullWidth size="small" margin="dense" value={data.name ?? ""}
          onChange={e => setField("name", e.target.value)} />
        <TextField label="Descrizione (facoltativa)" fullWidth size="small" margin="dense"
          multiline minRows={2} inputProps={{ maxLength: 500 }}
          placeholder="Es. rimborsi per trasferte o spese anticipate"
          helperText="Aiuta l'assistente a classificare meglio entrate ambigue"
          value={data.description ?? ""}
          onChange={e => setField("description", e.target.value)} />
      </>
    );

    if (entity === "subscription") return (
      <>
        <TextField label="Nome *" fullWidth size="small" margin="dense" value={data.name ?? ""}
          onChange={e => setField("name", e.target.value)} />
        <TextField label="Importo (€)" fullWidth size="small" margin="dense" type="number"
          value={data.amount ?? ""}
          onChange={e => setField("amount", e.target.value)} />
        <FormControl fullWidth size="small" margin="dense">
          <InputLabel>Frequenza</InputLabel>
          <Select label="Frequenza" value={data.sub_type ?? ""}
            onChange={e => setField("sub_type", e.target.value)}>
            <MenuItem value=""><em>Nessuno</em></MenuItem>
            {SUB_TYPES.map(t => <MenuItem key={t} value={t}>{t}</MenuItem>)}
          </Select>
        </FormControl>
        <TextField label="Ultima fattura" fullWidth size="small" margin="dense" type="date"
          value={data.last_billed ?? ""}
          slotProps={{ inputLabel: { shrink: true } }}
          onChange={e => setField("last_billed", e.target.value)} />
        <FormControl fullWidth size="small" margin="dense">
          <InputLabel>Conto</InputLabel>
          <Select label="Conto" value={data.account_id ?? ""}
            onChange={e => setField("account_id", e.target.value)}>
            <MenuItem value=""><em>Nessuno</em></MenuItem>
            {accounts.map(a => <MenuItem key={a.id} value={a.id}>{a.name}</MenuItem>)}
          </Select>
        </FormControl>
        <FormControl fullWidth size="small" margin="dense">
          <InputLabel>Categoria</InputLabel>
          <Select label="Categoria" value={data.category_id ?? ""}
            onChange={e => setField("category_id", e.target.value)}>
            <MenuItem value=""><em>Nessuna</em></MenuItem>
            {categories.map(c => <MenuItem key={c.id} value={c.id}>{c.name}</MenuItem>)}
          </Select>
        </FormControl>
      </>
    );

    if (entity === "expense") return (
      <>
        <TextField label="Descrizione *" fullWidth size="small" margin="dense" value={data.name ?? ""}
          onChange={e => setField("name", e.target.value)} />
        <TextField label="Importo (€) *" fullWidth size="small" margin="dense" type="number"
          value={data.amount ?? ""}
          onChange={e => setField("amount", e.target.value)} />
        <TextField label="Data *" fullWidth size="small" margin="dense" type="date"
          value={data.date ?? todayIso()}
          slotProps={{ inputLabel: { shrink: true } }}
          onChange={e => setField("date", e.target.value)} />
        <FormControl fullWidth size="small" margin="dense">
          <InputLabel>Categoria</InputLabel>
          <Select label="Categoria" value={data.category_id ?? ""}
            onChange={e => setField("category_id", e.target.value)}>
            <MenuItem value=""><em>Nessuna</em></MenuItem>
            {categories.map(c => <MenuItem key={c.id} value={c.id}>{c.name}</MenuItem>)}
          </Select>
        </FormControl>
        <FormControl fullWidth size="small" margin="dense">
          <InputLabel>Conto</InputLabel>
          <Select label="Conto" value={data.account_id ?? ""}
            onChange={e => setField("account_id", e.target.value)}>
            <MenuItem value=""><em>Nessuno</em></MenuItem>
            {accounts.map(a => <MenuItem key={a.id} value={a.id}>{a.name}</MenuItem>)}
          </Select>
        </FormControl>
      </>
    );

    if (entity === "income") return (
      <>
        <TextField label="Descrizione *" fullWidth size="small" margin="dense" value={data.name ?? ""}
          onChange={e => setField("name", e.target.value)} />
        <TextField label="Importo (€) *" fullWidth size="small" margin="dense" type="number"
          value={data.amount ?? ""}
          onChange={e => setField("amount", e.target.value)} />
        <TextField label="Data *" fullWidth size="small" margin="dense" type="date"
          value={data.date ?? todayIso()}
          slotProps={{ inputLabel: { shrink: true } }}
          onChange={e => setField("date", e.target.value)} />
        <FormControl fullWidth size="small" margin="dense">
          <InputLabel>Categoria entrata</InputLabel>
          <Select label="Categoria entrata" value={data.income_category_id ?? ""}
            onChange={e => {
              const category = incomeCategories.find(item => item.id === Number(e.target.value));
              setField("income_category_id", e.target.value);
              setField("income_category", category?.name ?? "");
            }}>
            <MenuItem value=""><em>Nessuno</em></MenuItem>
            {activeIncomeCategories(incomeCategories).map(category => (
              <MenuItem key={category.id} value={category.id}>{category.name}</MenuItem>
            ))}
          </Select>
        </FormControl>
        <FormControl fullWidth size="small" margin="dense">
          <InputLabel>Conto *</InputLabel>
          <Select label="Conto *" value={data.account_id ?? ""}
            onChange={e => setField("account_id", e.target.value)}>
            <MenuItem value=""><em>Nessuno</em></MenuItem>
            {accounts.map(a => <MenuItem key={a.id} value={a.id}>{a.name}</MenuItem>)}
          </Select>
        </FormControl>
      </>
    );

    if (entity === "transfer") {
      const fromId = data.from_account_id ?? "";
      return (
        <>
          <TextField label="Descrizione" fullWidth size="small" margin="dense" value={data.name ?? ""}
            onChange={e => setField("name", e.target.value)} />
          <TextField label="Importo (€) *" fullWidth size="small" margin="dense" type="number"
            value={data.amount ?? ""}
            onChange={e => setField("amount", e.target.value)} />
          <TextField label="Data *" fullWidth size="small" margin="dense" type="date"
            value={data.date ?? todayIso()}
            slotProps={{ inputLabel: { shrink: true } }}
            onChange={e => setField("date", e.target.value)} />
          <FormControl fullWidth size="small" margin="dense">
            <InputLabel>Da conto *</InputLabel>
            <Select label="Da conto *" value={fromId}
              onChange={e => setField("from_account_id", e.target.value)}>
              <MenuItem value=""><em>Nessuno</em></MenuItem>
              {accounts.map(a => <MenuItem key={a.id} value={a.id}>{a.name}</MenuItem>)}
            </Select>
          </FormControl>
          <FormControl fullWidth size="small" margin="dense">
            <InputLabel>A conto *</InputLabel>
            <Select label="A conto *" value={data.to_account_id ?? ""}
              onChange={e => setField("to_account_id", e.target.value)}>
              <MenuItem value=""><em>Nessuno</em></MenuItem>
              {accounts.filter(a => String(a.id) !== String(fromId)).map(a => (
                <MenuItem key={a.id} value={a.id}>{a.name}</MenuItem>
              ))}
            </Select>
          </FormControl>
        </>
      );
    }

    return null;
  }

  const ENTITY_LABELS: Record<EntityType, string> = {
    account: "Conto", category: "Categoria", incomeCategory: "Categoria entrata", subscription: "Abbonamento",
    expense: "Spesa", income: "Entrata", transfer: "Trasferimento",
  };

  // ---------------------------------------------------------------------------
  // Render
  // ---------------------------------------------------------------------------

  return (
    <Box sx={{ p: { xs: 1.5, sm: 3 }, width: "100%", maxWidth: 1400, mx: "auto", overflowX: "hidden" }}>
      {/* Header */}
      <Box sx={{ mb: 3 }}>
        <Typography component="h1" variant="h5" sx={{ fontWeight: 300, letterSpacing: "0.015em", color: PRIMARY, mb: 0.5 }}>
          Gestisci
        </Typography>
        <Typography variant="body2" color="text.secondary">
          Gestisci conti, categorie e budget, abbonamenti, entrate, spese e trasferimenti
        </Typography>
      </Box>

      {/* Banner setup post-onboarding */}
      {showSetupBanner && (
        <Alert
          severity="warning"
          onClose={() => setSetupBannerDismissed(true)}
          sx={{ mb: 3, borderRadius: 2, fontSize: "0.85rem", alignItems: "flex-start" }}
        >
          <Box>
            <strong>Completa la configurazione del tuo spazio</strong>
            <Box component="ul" sx={{ m: 0, mt: 0.5, pl: 2.5, lineHeight: 1.8 }}>
              {missingAccounts && <li>Aggiungi almeno un <strong>conto</strong> (es. carta, contanti) dalla tab <em>Conti</em></li>}
              {missingBudgets && <li>Imposta un <strong>budget mensile</strong> per le tue categorie di spesa dalla tab <em>Categorie</em></li>}
            </Box>
          </Box>
        </Alert>
      )}

      {/* Card con tabs */}
      <Card sx={{ border: `1px solid ${BORDER}`, borderRadius: 2, overflow: "hidden" }}>
        {isMobile ? (
          <Box
            data-tour="spazio-tabs"
            role="tablist"
            aria-label="Sezioni di Gestisci"
            sx={{
              borderBottom: `1px solid ${BORDER}`,
              display: "grid",
              gridTemplateColumns: "repeat(3, 1fr)",
              gap: 0.5,
              p: 1,
            }}
          >
            {SPAZIO_TAB_ICONS.map(({ label, Icon }, index) => (
              <Box
                key={label}
                component="button"
                type="button"
                role="tab"
                aria-selected={tab === index}
                aria-label={label}
                onClick={() => setTab(index)}
                sx={{
                  display: "grid",
                  justifyItems: "center",
                  gap: 0.4,
                  border: "none",
                  borderRadius: 1.5,
                  py: 1,
                  cursor: "pointer",
                  color: tab === index ? PRIMARY : "text.secondary",
                  bgcolor: tab === index ? "rgba(233,241,234,0.07)" : "transparent",
                  minHeight: 44,
                }}
              >
                <Icon size={20} strokeWidth={1.75} aria-hidden="true" />
              </Box>
            ))}
          </Box>
        ) : (
          <Tabs
            value={tab}
            onChange={(_, v) => setTab(v)}
            variant="scrollable"
            scrollButtons="auto"
            data-tour="spazio-tabs"
            sx={{
              borderBottom: `1px solid ${BORDER}`,
              px: 2,
              "& .MuiTab-root": { fontWeight: 600, fontSize: "0.85rem", textTransform: "none", minHeight: 48 },
              "& .Mui-selected": { color: PRIMARY },
              "& .MuiTabs-indicator": { bgcolor: PRIMARY },
            }}
          >
            <Tab label="Conti" />
            <Tab label="Categorie" />
            <Tab label="Abbonamenti" />
            <Tab label="Spese" />
            <Tab label="Entrate" />
            <Tab label="Trasferimenti" />
          </Tabs>
        )}

        <CardContent sx={{ p: 0, "&:last-child": { pb: 0 } }}>
          {tab === 0 && renderAccounts()}
          {tab === 1 && renderCategories()}
          {tab === 2 && renderSubscriptions()}
          {tab === 3 && renderExpenses()}
          {tab === 4 && renderIncomes()}
          {tab === 5 && renderTransfers()}
        </CardContent>
      </Card>

      {/* Dialog add/edit */}
      <Dialog
        open={dialog.open}
        onClose={closeDialog}
        maxWidth="xs"
        fullWidth
        slotProps={{ paper: { "data-tour": "entity-dialog" } as Record<string, string> }}
      >
        <DialogTitle sx={{ fontWeight: 500, fontSize: "1rem", color: PRIMARY }}>
          {dialog.mode === "add" ? "Aggiungi" : "Modifica"} {ENTITY_LABELS[dialog.entity]}
        </DialogTitle>
        <DialogContent sx={{ pt: 0 }}>
          {renderDialogFields()}
        </DialogContent>
        <DialogActions sx={{ px: 3, pb: 2 }}>
          <Button onClick={closeDialog} data-tour="entity-dialog-close" sx={{ color: "text.secondary", textTransform: "none" }}>
            Annulla
          </Button>
          <Button
            variant="contained"
            onClick={handleSave}
            sx={{ bgcolor: PRIMARY, textTransform: "none", fontWeight: 600, "&:hover": { bgcolor: "#4AA7AE" } }}
          >
            {dialog.mode === "add" ? "Aggiungi" : "Salva"}
          </Button>
        </DialogActions>
      </Dialog>

      <AppSnackbar snack={snack} onClose={closeSnack} />
    </Box>
  );
}

// ---------------------------------------------------------------------------
// Sotto-componenti
// ---------------------------------------------------------------------------

function TabToolbar({
  label, onAdd, loading, children,
}: { label: string; onAdd: () => void; loading?: boolean; children?: React.ReactNode }) {
  return (
    <Box sx={{ display: "flex", alignItems: "center", gap: 1, px: 2, py: 1.5, flexWrap: "wrap", borderBottom: `1px solid ${BORDER}` }}>
      <Typography variant="subtitle2" sx={{ fontWeight: 500, color: "var(--color-text)", flexGrow: 1 }}>
        {label}
      </Typography>
      {children}
      {loading && <CircularProgress size={16} sx={{ color: "text.secondary" }} />}
      <Button
        variant="contained"
        size="small"
        startIcon={<Plus size={14} />}
        onClick={onAdd}
        sx={{
          bgcolor: PRIMARY, textTransform: "none", fontWeight: 600, fontSize: "0.8rem",
          px: 1.5, py: 0.5, "&:hover": { bgcolor: "#4AA7AE" },
        }}
      >
        Aggiungi
      </Button>
    </Box>
  );
}

function RowActions({ onEdit, onDelete, editTourAttr }: { onEdit: () => void; onDelete: () => void; editTourAttr?: string }) {
  return (
    <Box sx={{ display: "flex", gap: 0.5, justifyContent: "flex-end" }}>
      <Tooltip title="Modifica">
        <IconButton aria-label="Modifica" onClick={onEdit} data-tour={editTourAttr} sx={{ width: 44, height: 44, color: "text.secondary", "&:hover": { color: "primary.main" } }}>
          <Pencil size={14} />
        </IconButton>
      </Tooltip>
      <Tooltip title="Elimina">
        <IconButton aria-label="Elimina" onClick={onDelete} sx={{ width: 44, height: 44, color: "text.secondary", "&:hover": { color: "error.main" } }}>
          <Trash2 size={14} />
        </IconButton>
      </Tooltip>
    </Box>
  );
}

function DateRangeFilter({
  start, end, onChange,
}: { start: string; end: string; onChange: (start: string, end: string) => void }) {
  const [anchorEl, setAnchorEl] = useState<HTMLElement | null>(null);
  const activePreset = DATE_RANGE_PRESETS.find(p => p.start() === start && p.end() === end);
  const label = activePreset ? activePreset.label : `${formatDateIt(start)} – ${formatDateIt(end)}`;

  function applyRange(rangeStart: string, rangeEnd: string) {
    onChange(rangeStart, rangeEnd);
    setAnchorEl(null);
  }

  return (
    <>
      <Button
        variant="outlined"
        size="small"
        startIcon={<CalendarDays size={14} />}
        onClick={e => setAnchorEl(e.currentTarget)}
        sx={{
          fontSize: "0.75rem", textTransform: "none", fontWeight: 500, minHeight: 40,
          color: "text.primary", borderColor: "divider", whiteSpace: "nowrap",
        }}
      >
        {label}
      </Button>
      <Menu anchorEl={anchorEl} open={Boolean(anchorEl)} onClose={() => setAnchorEl(null)}>
        {DATE_RANGE_PRESETS.map(p => (
          <MenuItem
            key={p.label}
            selected={p.start() === start && p.end() === end}
            onClick={() => applyRange(p.start(), p.end())}
            sx={{ fontSize: "0.85rem" }}
          >
            {p.label}
          </MenuItem>
        ))}
        <Divider sx={{ my: 0.5 }} />
        <Box sx={{ px: 1, py: 1 }}>
          <Typography variant="caption" color="text.secondary" sx={{ px: 0.5 }}>Intervallo personalizzato</Typography>
          <SwipeCalendar mode="range" start={start} end={end} onRangeSelected={applyRange} />
        </Box>
      </Menu>
    </>
  );
}

function SearchInput({ value, onChange, placeholder = "Cerca..." }: {
  value: string; onChange: (v: string) => void; placeholder?: string;
}) {
  return (
    <TextField
      size="small" value={value} placeholder={placeholder}
      onChange={e => onChange(e.target.value)}
      sx={{ "& .MuiInputBase-input": { fontSize: "0.75rem" }, width: { xs: "100%", sm: 180 } }}
    />
  );
}

function FilterSelect({ label, value, onChange, options }: {
  label: string; value: string; onChange: (v: string) => void;
  options: { value: string; label: string }[];
}) {
  return (
    <FormControl size="small" sx={{ minWidth: { xs: "100%", sm: 130 } }}>
      <InputLabel sx={{ fontSize: "0.75rem" }}>{label}</InputLabel>
      <Select
        label={label} value={value}
        onChange={e => onChange(e.target.value as string)}
        sx={{ fontSize: "0.75rem" }}
      >
        <MenuItem value=""><em>Tutti</em></MenuItem>
        {options.map(o => (
          <MenuItem key={o.value} value={o.value} sx={{ fontSize: "0.8rem", textTransform: "capitalize" }}>
            {o.label}
          </MenuItem>
        ))}
      </Select>
    </FormControl>
  );
}
