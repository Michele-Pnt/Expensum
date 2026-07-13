"use client";

import { useEffect, useState, useCallback, useMemo } from "react";
import {
  Box, Card, CardContent, Tab, Tabs, Typography, Table, TableBody,
  TableCell, TableContainer, TableHead, TableRow, TablePagination,
  IconButton, Button, Dialog, DialogTitle, DialogContent, DialogActions,
  TextField, Select, MenuItem, FormControl, InputLabel, Chip, Menu,
  CircularProgress, Snackbar, Alert, Tooltip, TableSortLabel,
} from "@mui/material";
import { Plus, Pencil, Trash2, Check, X } from "lucide-react";
import { getCsrfToken } from "@/lib/csrf";

// ---------------------------------------------------------------------------
// Tipi
// ---------------------------------------------------------------------------

interface Account {
  id: number; name: string; account_type: string | null;
  current_balance: number; opening_balance: number; currency: string;
}
interface Category { id: number; name: string; monthly_budget: number | null }
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
  income_type: string; account: string; account_id: number | null;
}
interface Transfer {
  id: number; date: string; name: string; amount: number;
  from_account_id: number; to_account_id: number;
}

type DialogMode = "add" | "edit";
type EntityType = "account" | "category" | "subscription" | "expense" | "income" | "transfer";

// ---------------------------------------------------------------------------
// Colori / costanti
// ---------------------------------------------------------------------------

const PRIMARY = "#1A3673";
const ACCENT = "#C5A059";
const BORDER = "#E5E2DC";

const CELL_SX = { fontSize: "0.8rem", py: 1 };
const HEAD_SX = { fontSize: "0.75rem", fontWeight: 700, color: "#6B7280", py: 1 };

const ENTITY_PATH: Record<EntityType, string> = {
  account: "accounts",
  category: "categories",
  subscription: "subscriptions",
  expense: "expenses",
  income: "incomes",
  transfer: "transfers",
};

const ACCOUNT_TYPES = ["Conto corrente", "Carta di credito", "Risparmio", "Contanti", "Investimento"];
const SUB_TYPES = ["Settimanale", "Mensile", "Bimestrale", "Trimestrale", "Semestrale", "Annuale"];
const INCOME_TYPES = ["stipendio", "freelance", "investimento", "regalo", "rimborso", "altro"];

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function getTelegramInitData(): string {
  if (typeof window === "undefined") return "";
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  return (window as any).Telegram?.WebApp?.initData ?? "";
}

async function buildHeaders(): Promise<HeadersInit> {
  const init = getTelegramInitData();
  const csrfToken = await getCsrfToken();
  const headers: Record<string, string> = {
    "Content-Type": "application/json",
    "X-CSRFToken": csrfToken,
  };
  if (init) headers["X-Telegram-Init-Data"] = init;
  return headers;
}

function fmtCurrency(n: number | null | undefined): string {
  if (n == null) return "—";
  return n.toLocaleString("it-IT", { style: "currency", currency: "EUR" });
}

function todayIso(): string {
  return new Date().toISOString().slice(0, 10);
}

function monthStartIso(): string {
  const d = new Date();
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-01`;
}

// ---------------------------------------------------------------------------
// Componente principale
// ---------------------------------------------------------------------------

export default function SpazioPage() {
  const [tab, setTab] = useState(0);

  // Dati
  const [accounts, setAccounts] = useState<Account[]>([]);
  const [categories, setCategories] = useState<Category[]>([]);
  const [subscriptions, setSubscriptions] = useState<Subscription[]>([]);
  const [expenses, setExpenses] = useState<Expense[]>([]);
  const [incomes, setIncomes] = useState<Income[]>([]);
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
  const [incType, setIncType] = useState("");
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

  // Loading
  const [loading, setLoading] = useState<Record<string, boolean>>({});

  // Dialog
  const [dialog, setDialog] = useState<{
    open: boolean; mode: DialogMode; entity: EntityType; data: Record<string, string | number | null>;
  }>({ open: false, mode: "add", entity: "account", data: {} });

  // Snackbar
  const [snack, setSnack] = useState<{ open: boolean; msg: string; severity: "success" | "error" }>({
    open: false, msg: "", severity: "success",
  });

  // Menu di modifica rapida categoria (click sul chip in tabella spese)
  const [catMenu, setCatMenu] = useState<{ anchorEl: HTMLElement; expenseId: number } | null>(null);

  // Suggerimenti budget (calcolati on-demand, non persistiti)
  const [suggestions, setSuggestions] = useState<Record<string, number>>({});
  const [dismissed, setDismissed] = useState<Set<string>>(new Set());
  const [loadingSuggestions, setLoadingSuggestions] = useState(false);

  // Banner setup post-onboarding
  const [setupBannerDismissed, setSetupBannerDismissed] = useState(false);
  const missingAccounts = !loading.accounts && accounts.length === 0;
  const missingBudgets = !loading.categories && categories.length > 0 && categories.every(c => c.monthly_budget == null);
  const showSetupBanner = !setupBannerDismissed && (missingAccounts || missingBudgets);

  // ---------------------------------------------------------------------------
  // Fetch
  // ---------------------------------------------------------------------------

  const fetchAccounts = useCallback(async () => {
    setLoading(l => ({ ...l, accounts: true }));
    try {
      const res = await fetch("/api/space/accounts", { headers: await buildHeaders() });
      const json = await res.json();
      setAccounts(json.accounts ?? []);
    } finally {
      setLoading(l => ({ ...l, accounts: false }));
    }
  }, []);

  const fetchCategories = useCallback(async () => {
    setLoading(l => ({ ...l, categories: true }));
    try {
      const res = await fetch("/api/space/categories", { headers: await buildHeaders() });
      const json = await res.json();
      setCategories(json.categories ?? []);
    } finally {
      setLoading(l => ({ ...l, categories: false }));
    }
  }, []);

  const fetchSuggestions = useCallback(async () => {
    setLoadingSuggestions(true);
    try {
      const res = await fetch("/api/space/categories/suggestions", { headers: await buildHeaders() });
      if (res.ok) {
        const json = await res.json();
        setSuggestions(json.suggestions ?? {});
      }
    } finally {
      setLoadingSuggestions(false);
    }
  }, []);

  const fetchSubscriptions = useCallback(async () => {
    setLoading(l => ({ ...l, subscriptions: true }));
    try {
      const res = await fetch("/api/space/subscriptions", { headers: await buildHeaders() });
      const json = await res.json();
      setSubscriptions(json.subscriptions ?? []);
    } finally {
      setLoading(l => ({ ...l, subscriptions: false }));
    }
  }, []);

  const fetchExpenses = useCallback(async (
    page = expPage, rpp = expRowsPP, start = expStart, end = expEnd,
    search = expSearch, catId = expCatId, accId = expAccId,
    sortBy = expSortBy, sortDir = expSortDir,
  ) => {
    setLoading(l => ({ ...l, expenses: true }));
    try {
      const params = new URLSearchParams({ limit: String(rpp), offset: String(page * rpp), start, end });
      if (search) params.set("search", search);
      if (catId) params.set("category_id", catId);
      if (accId) params.set("account_id", accId);
      params.set("sort_by", sortBy);
      params.set("sort_dir", sortDir);
      const res = await fetch(`/api/space/expenses?${params}`, { headers: await buildHeaders() });
      const json = await res.json();
      setExpenses(json.expenses ?? []);
      setExpTotal(json.total ?? 0);
    } finally {
      setLoading(l => ({ ...l, expenses: false }));
    }
  }, [expPage, expRowsPP, expStart, expEnd, expSearch, expCatId, expAccId, expSortBy, expSortDir]);

  const fetchIncomes = useCallback(async (
    page = incPage, rpp = incRowsPP, start = incStart, end = incEnd,
    search = incSearch, type = incType, accId = incAccId,
    sortBy = incSortBy, sortDir = incSortDir,
  ) => {
    setLoading(l => ({ ...l, incomes: true }));
    try {
      const params = new URLSearchParams({ limit: String(rpp), offset: String(page * rpp), start, end });
      if (search) params.set("search", search);
      if (type) params.set("income_type", type);
      if (accId) params.set("account_id", accId);
      params.set("sort_by", sortBy);
      params.set("sort_dir", sortDir);
      const res = await fetch(`/api/space/incomes?${params}`, { headers: await buildHeaders() });
      const json = await res.json();
      setIncomes(json.incomes ?? []);
      setIncTotal(json.total ?? 0);
    } finally {
      setLoading(l => ({ ...l, incomes: false }));
    }
  }, [incPage, incRowsPP, incStart, incEnd, incSearch, incType, incAccId, incSortBy, incSortDir]);

  const fetchTransfers = useCallback(async (start = monthStartIso(), end = todayIso()) => {
    setLoading(l => ({ ...l, transfers: true }));
    try {
      const params = new URLSearchParams({ start, end });
      const res = await fetch(`/api/space/transfers?${params}`, { headers: await buildHeaders() });
      const json = await res.json();
      setTransfers(json.transfers ?? []);
    } finally {
      setLoading(l => ({ ...l, transfers: false }));
    }
  }, []);

  // Carica tutto al mount e poi su cambio tab
  useEffect(() => { fetchAccounts(); fetchCategories(); fetchSubscriptions(); fetchSuggestions(); }, [fetchAccounts, fetchCategories, fetchSubscriptions, fetchSuggestions]);
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
      category: { name: "", monthly_budget: "" },
      subscription: { name: "", amount: "", sub_type: "", last_billed: "", account_id: "", category_id: "" },
      expense: { name: "", amount: "", date: todayIso(), category: "", category_id: "", account_id: "" },
      income: { name: "", amount: "", date: todayIso(), income_type: "", account_id: "" },
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
    const url = mode === "add" ? `/api/space/${path}` : `/api/space/${path}/${data.id}`;
    const method = mode === "add" ? "POST" : "PUT";

    // Per le spese, risolvi category_id → nome categoria per la POST
    let bodyData = { ...data };
    if (entity === "expense" && mode === "add") {
      const cat = categories.find(c => c.id === Number(data.category_id));
      bodyData = { ...bodyData, category: cat?.name ?? "" };
    }

    try {
      const res = await fetch(url, {
        method,
        headers: await buildHeaders(),
        body: JSON.stringify(bodyData),
      });
      if (!res.ok) {
        const err = await res.json().catch(() => ({}));
        throw new Error(err.error || "Errore sconosciuto");
      }
      closeDialog();
      setSnack({ open: true, msg: mode === "add" ? "Aggiunto con successo" : "Aggiornato con successo", severity: "success" });
      refreshEntity(entity);
    } catch (e: unknown) {
      const msg = e instanceof Error ? e.message : "Errore";
      setSnack({ open: true, msg, severity: "error" });
    }
  }

  // ---------------------------------------------------------------------------
  // Modifica rapida categoria (click sul chip in tabella spese)
  // ---------------------------------------------------------------------------

  async function quickUpdateCategory(expenseId: number, category: Category) {
    setCatMenu(null);
    try {
      const res = await fetch(`/api/space/expenses/${expenseId}`, {
        method: "PUT",
        headers: await buildHeaders(),
        body: JSON.stringify({ category_id: category.id }),
      });
      if (!res.ok) {
        const err = await res.json().catch(() => ({}));
        throw new Error(err.error || "Errore sconosciuto");
      }
      setExpenses(prev => prev.map(e =>
        e.id === expenseId ? { ...e, category_id: category.id, category: category.name } : e
      ));
      setSnack({ open: true, msg: "Categoria aggiornata", severity: "success" });
    } catch (e: unknown) {
      const msg = e instanceof Error ? e.message : "Errore";
      setSnack({ open: true, msg, severity: "error" });
    }
  }

  // ---------------------------------------------------------------------------
  // Delete
  // ---------------------------------------------------------------------------

  async function handleDelete(entity: EntityType, id: number) {
    try {
      const res = await fetch(`/api/space/${ENTITY_PATH[entity]}/${id}`, {
        method: "DELETE",
        headers: await buildHeaders(),
      });
      if (!res.ok) {
        const err = await res.json().catch(() => ({}));
        throw new Error(err.error || "Errore sconosciuto");
      }
      setSnack({ open: true, msg: "Eliminato", severity: "success" });
      refreshEntity(entity);
    } catch (e: unknown) {
      const msg = e instanceof Error ? e.message : "Errore";
      setSnack({ open: true, msg, severity: "error" });
    }
  }

  function refreshEntity(entity: EntityType) {
    if (entity === "account") fetchAccounts();
    else if (entity === "category") fetchCategories();
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
      const res = await fetch(`/api/space/categories/${cat.id}/accept-suggestion`, {
        method: "POST",
        headers: await buildHeaders(),
        body: JSON.stringify({ suggested_budget: suggested }),
      });
      if (!res.ok) {
        const err = await res.json().catch(() => ({}));
        throw new Error(err.error || "Errore");
      }
      // Dismetti subito così non ricompare dopo il ricalcolo
      setDismissed(prev => new Set(prev).add(cat.name));
      setSnack({ open: true, msg: `Budget ${cat.name} aggiornato a ${fmtCurrency(suggested)}`, severity: "success" });
      await fetchCategories();
    } catch (e: unknown) {
      const msg = e instanceof Error ? e.message : "Errore";
      setSnack({ open: true, msg, severity: "error" });
    }
  }

  function dismissSuggestion(catName: string) {
    setDismissed(prev => new Set(prev).add(catName));
  }

  async function acceptAllSuggestions() {
    const toAccept = Object.entries(suggestions).filter(([name]) => !dismissed.has(name));
    for (const [name, amount] of toAccept) {
      const cat = categories.find(c => c.name === name);
      if (cat) await acceptSuggestion(cat, amount);
    }
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

  // ---------------------------------------------------------------------------
  // Render tabelle
  // ---------------------------------------------------------------------------

  function renderAccounts() {
    return (
      <Box data-tour="spazio-conti">
        <TabToolbar label="Conti" onAdd={() => openAdd("account")} loading={loading.accounts} />
        <TableContainer sx={{ overflowX: "auto" }}>
          <Table size="small" sx={{ minWidth: 500 }}>
            <TableHead>
              <TableRow>
                <TableCell sx={HEAD_SX}>Nome</TableCell>
                <TableCell sx={HEAD_SX}>Tipo</TableCell>
                <TableCell sx={{ ...HEAD_SX, textAlign: "right" }}>Saldo</TableCell>
                <TableCell sx={{ ...HEAD_SX, width: 80 }} />
              </TableRow>
            </TableHead>
            <TableBody>
              {accounts.map(row => (
                <TableRow key={row.id} hover>
                  <TableCell sx={CELL_SX}>{row.name}</TableCell>
                  <TableCell sx={CELL_SX}>
                    {row.account_type
                      ? <Chip label={row.account_type} size="small" sx={{ fontSize: "0.7rem" }} />
                      : <span style={{ color: "#9CA3AF" }}>—</span>}
                  </TableCell>
                  <TableCell sx={{ ...CELL_SX, textAlign: "right", fontWeight: 600, color: row.current_balance >= 0 ? PRIMARY : "#EF4444" }}>
                    {fmtCurrency(row.current_balance)}
                  </TableCell>
                  <TableCell sx={CELL_SX}>
                    <RowActions
                      onEdit={() => openEdit("account", {
                        id: row.id, name: row.name, account_type: row.account_type ?? "",
                        balance: row.opening_balance,
                      })}
                      onDelete={() => handleDelete("account", row.id)}
                    />
                  </TableCell>
                </TableRow>
              ))}
              {!loading.accounts && accounts.length === 0 && (
                <EmptyRow colSpan={4} />
              )}
            </TableBody>
          </Table>
        </TableContainer>
      </Box>
    );
  }

  function renderCategories() {
    const activeSuggestions = Object.entries(suggestions).filter(([name]) => !dismissed.has(name));
    const hasSuggestions = activeSuggestions.length > 0;

    function handleCatSort(field: string) {
      const newDir = catSortBy === field ? (catSortDir === "asc" ? "desc" : "asc") : "asc";
      setCatSortBy(field as "name" | "budget");
      setCatSortDir(newDir as "asc" | "desc");
    }

    return (
      <Box data-tour="spazio-categorie">
        <TabToolbar label="Categorie" onAdd={() => openAdd("category")} loading={loading.categories || loadingSuggestions}>
          <SearchInput value={catSearch} onChange={setCatSearch} placeholder="Cerca categoria..." />
        </TabToolbar>

        {hasSuggestions && (
          <Alert
            severity="info"
            sx={{ mb: 2, borderRadius: 2 }}
            action={
              <Button
                size="small"
                variant="contained"
                disableElevation
                sx={{ bgcolor: PRIMARY, color: "#fff", fontSize: "0.75rem", whiteSpace: "nowrap",
                      "&:hover": { bgcolor: "#142d5e" } }}
                onClick={acceptAllSuggestions}
              >
                Accetta tutti
              </Button>
            }
          >
            Ho <strong>{activeSuggestions.length}</strong> consigli budget basati sulle tue spese recenti.
          </Alert>
        )}

        <TableContainer sx={{ overflowX: "auto" }}>
          <Table size="small" sx={{ minWidth: hasSuggestions ? 620 : 400 }}>
            <TableHead>
              <TableRow>
                <SortableHead label="Nome" field="name" sortBy={catSortBy} sortDir={catSortDir} onSort={handleCatSort} />
                <SortableHead label="Budget mensile" field="budget" sortBy={catSortBy} sortDir={catSortDir} onSort={handleCatSort} sx={{ textAlign: "right" }} />
                {hasSuggestions && <TableCell sx={{ ...HEAD_SX, textAlign: "right" }}>Consiglio</TableCell>}
                <TableCell sx={{ ...HEAD_SX, width: 80 }} />
              </TableRow>
            </TableHead>
            <TableBody>
              {filteredCats.map(row => {
                const suggested = suggestions[row.name];
                const showSuggestion = suggested != null && !dismissed.has(row.name);
                const delta = suggested != null && row.monthly_budget != null
                  ? (suggested - row.monthly_budget) / row.monthly_budget
                  : null;
                const trendIcon = delta == null ? "" : delta > 0.05 ? " ↑" : delta < -0.05 ? " ↓" : " ≈";
                return (
                  <TableRow key={row.id} hover>
                    <TableCell sx={CELL_SX}>{row.name}</TableCell>
                    <TableCell sx={{ ...CELL_SX, textAlign: "right", color: ACCENT }}>
                      {row.monthly_budget != null ? fmtCurrency(row.monthly_budget) : <span style={{ color: "#9CA3AF" }}>—</span>}
                    </TableCell>
                    {hasSuggestions && (
                      <TableCell sx={{ ...CELL_SX, textAlign: "right" }}>
                        {showSuggestion ? (
                          <Box sx={{ display: "flex", alignItems: "center", justifyContent: "flex-end", gap: 0.5 }}>
                            <Typography variant="caption" sx={{ color: PRIMARY, fontWeight: 600 }}>
                              {fmtCurrency(suggested)}{trendIcon}
                            </Typography>
                            <Tooltip title="Accetta">
                              <IconButton size="small" sx={{ color: "#16A34A" }} onClick={() => acceptSuggestion(row, suggested)}>
                                <Check size={14} />
                              </IconButton>
                            </Tooltip>
                            <Tooltip title="Scarta">
                              <IconButton size="small" sx={{ color: "#9CA3AF" }} onClick={() => dismissSuggestion(row.name)}>
                                <X size={14} />
                              </IconButton>
                            </Tooltip>
                          </Box>
                        ) : null}
                      </TableCell>
                    )}
                    <TableCell sx={CELL_SX}>
                      <RowActions
                        onEdit={() => openEdit("category", { id: row.id, name: row.name, monthly_budget: row.monthly_budget ?? "" })}
                        onDelete={() => handleDelete("category", row.id)}
                      />
                    </TableCell>
                  </TableRow>
                );
              })}
              {!loading.categories && filteredCats.length === 0 && <EmptyRow colSpan={hasSuggestions ? 4 : 3} />}
            </TableBody>
          </Table>
        </TableContainer>
      </Box>
    );
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
        <TableContainer sx={{ overflowX: "auto" }}>
          <Table size="small" sx={{ minWidth: 700 }}>
            <TableHead>
              <TableRow>
                <SortableHead label="Nome" field="name" sortBy={subSortBy} sortDir={subSortDir} onSort={handleSubSort} />
                <SortableHead label="Importo" field="amount" sortBy={subSortBy} sortDir={subSortDir} onSort={handleSubSort} sx={{ textAlign: "right" }} />
                <TableCell sx={HEAD_SX}>Frequenza</TableCell>
                <TableCell sx={HEAD_SX}>Ultima fattura</TableCell>
                <TableCell sx={HEAD_SX}>Conto</TableCell>
                <TableCell sx={{ ...HEAD_SX, width: 80 }} />
              </TableRow>
            </TableHead>
            <TableBody>
              {filteredSubs.map(row => (
                <TableRow key={row.id} hover>
                  <TableCell sx={CELL_SX}>{row.name}</TableCell>
                  <TableCell sx={{ ...CELL_SX, textAlign: "right", color: ACCENT, fontWeight: 600 }}>
                    {row.amount != null ? fmtCurrency(row.amount) : <span style={{ color: "#9CA3AF" }}>—</span>}
                  </TableCell>
                  <TableCell sx={CELL_SX}>
                    {row.sub_type
                      ? <Chip label={row.sub_type} size="small" sx={{ fontSize: "0.7rem", textTransform: "capitalize" }} />
                      : <span style={{ color: "#9CA3AF" }}>—</span>}
                  </TableCell>
                  <TableCell sx={{ ...CELL_SX, color: "#6B7280" }}>{row.last_billed ?? "—"}</TableCell>
                  <TableCell sx={{ ...CELL_SX, color: "#6B7280" }}>{row.account_name || "—"}</TableCell>
                  <TableCell sx={CELL_SX}>
                    <RowActions
                      onEdit={() => openEdit("subscription", {
                        id: row.id, name: row.name,
                        amount: row.amount ?? "", sub_type: row.sub_type ?? "",
                        last_billed: row.last_billed ?? "", account_id: row.account_id ?? "",
                        category_id: row.category_id ?? "",
                      })}
                      onDelete={() => handleDelete("subscription", row.id)}
                    />
                  </TableCell>
                </TableRow>
              ))}
              {!loading.subscriptions && filteredSubs.length === 0 && <EmptyRow colSpan={6} />}
            </TableBody>
          </Table>
        </TableContainer>
      </>
    );
  }

  function renderExpenses() {
    function onExpSearch(v: string) { setExpSearch(v); setExpPage(0); fetchExpenses(0, expRowsPP, expStart, expEnd, v, expCatId, expAccId, expSortBy, expSortDir); }
    function onExpCat(v: string) { setExpCatId(v); setExpPage(0); fetchExpenses(0, expRowsPP, expStart, expEnd, expSearch, v, expAccId, expSortBy, expSortDir); }
    function onExpAcc(v: string) { setExpAccId(v); setExpPage(0); fetchExpenses(0, expRowsPP, expStart, expEnd, expSearch, expCatId, v, expSortBy, expSortDir); }
    function handleExpSort(field: string) {
      const newDir: "asc" | "desc" = expSortBy === field ? (expSortDir === "asc" ? "desc" : "asc") : "asc";
      setExpSortBy(field); setExpSortDir(newDir); setExpPage(0);
      fetchExpenses(0, expRowsPP, expStart, expEnd, expSearch, expCatId, expAccId, field, newDir);
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
            onStart={v => { setExpStart(v); setExpPage(0); fetchExpenses(0, expRowsPP, v, expEnd, expSearch, expCatId, expAccId, expSortBy, expSortDir); }}
            onEnd={v => { setExpEnd(v); setExpPage(0); fetchExpenses(0, expRowsPP, expStart, v, expSearch, expCatId, expAccId, expSortBy, expSortDir); }}
          />
        </TabToolbar>
        <TableContainer sx={{ overflowX: "auto" }}>
          <Table size="small" sx={{ minWidth: 700 }}>
            <TableHead>
              <TableRow>
                <SortableHead label="Data" field="date" sortBy={expSortBy} sortDir={expSortDir} onSort={handleExpSort} />
                <SortableHead label="Descrizione" field="name" sortBy={expSortBy} sortDir={expSortDir} onSort={handleExpSort} />
                <SortableHead label="Importo" field="amount" sortBy={expSortBy} sortDir={expSortDir} onSort={handleExpSort} sx={{ textAlign: "right" }} />
                <TableCell sx={HEAD_SX}>Categoria</TableCell>
                <TableCell sx={HEAD_SX}>Conto</TableCell>
                <TableCell sx={{ ...HEAD_SX, width: 80 }} />
              </TableRow>
            </TableHead>
            <TableBody>
              {expenses.map(row => (
                <TableRow key={row.id} hover>
                  <TableCell sx={{ ...CELL_SX, color: "#6B7280" }}>{row.date}</TableCell>
                  <TableCell sx={CELL_SX}>{row.name}</TableCell>
                  <TableCell sx={{ ...CELL_SX, textAlign: "right", color: ACCENT, fontWeight: 600 }}>
                    {fmtCurrency(row.amount)}
                  </TableCell>
                  <TableCell sx={CELL_SX}>
                    {row.category
                      ? (
                        <Chip
                          label={row.category}
                          size="small"
                          clickable
                          onClick={e => setCatMenu({ anchorEl: e.currentTarget, expenseId: row.id })}
                          sx={{ fontSize: "0.7rem", bgcolor: "#F0EDE8" }}
                        />
                      )
                      : (
                        <Chip
                          label="Assegna categoria"
                          size="small"
                          clickable
                          variant="outlined"
                          onClick={e => setCatMenu({ anchorEl: e.currentTarget, expenseId: row.id })}
                          sx={{ fontSize: "0.7rem", color: "#9CA3AF", borderStyle: "dashed" }}
                        />
                      )}
                  </TableCell>
                  <TableCell sx={{ ...CELL_SX, color: "#6B7280" }}>{row.account || "—"}</TableCell>
                  <TableCell sx={CELL_SX}>
                    <RowActions
                      onEdit={() => openEdit("expense", {
                        id: row.id, name: row.name, amount: row.amount,
                        date: row.date, category_id: row.category_id ?? "",
                        account_id: row.account_id ?? "",
                      })}
                      onDelete={() => handleDelete("expense", row.id)}
                    />
                  </TableCell>
                </TableRow>
              ))}
              {!loading.expenses && expenses.length === 0 && <EmptyRow colSpan={6} />}
            </TableBody>
          </Table>
        </TableContainer>
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
    function onIncSearch(v: string) { setIncSearch(v); setIncPage(0); fetchIncomes(0, incRowsPP, incStart, incEnd, v, incType, incAccId, incSortBy, incSortDir); }
    function onIncType(v: string) { setIncType(v); setIncPage(0); fetchIncomes(0, incRowsPP, incStart, incEnd, incSearch, v, incAccId, incSortBy, incSortDir); }
    function onIncAcc(v: string) { setIncAccId(v); setIncPage(0); fetchIncomes(0, incRowsPP, incStart, incEnd, incSearch, incType, v, incSortBy, incSortDir); }
    function handleIncSort(field: string) {
      const newDir: "asc" | "desc" = incSortBy === field ? (incSortDir === "asc" ? "desc" : "asc") : "asc";
      setIncSortBy(field); setIncSortDir(newDir); setIncPage(0);
      fetchIncomes(0, incRowsPP, incStart, incEnd, incSearch, incType, incAccId, field, newDir);
    }

    return (
      <>
        <TabToolbar label="Entrate" onAdd={() => openAdd("income")} loading={loading.incomes}>
          <SearchInput value={incSearch} onChange={onIncSearch} placeholder="Cerca entrata..." />
          <FilterSelect
            label="Tipo"
            value={incType}
            onChange={onIncType}
            options={INCOME_TYPES.map(t => ({ value: t, label: t }))}
          />
          <FilterSelect
            label="Conto"
            value={incAccId}
            onChange={onIncAcc}
            options={accounts.map(a => ({ value: String(a.id), label: a.name }))}
          />
          <DateRangeFilter
            start={incStart} end={incEnd}
            onStart={v => { setIncStart(v); setIncPage(0); fetchIncomes(0, incRowsPP, v, incEnd, incSearch, incType, incAccId, incSortBy, incSortDir); }}
            onEnd={v => { setIncEnd(v); setIncPage(0); fetchIncomes(0, incRowsPP, incStart, v, incSearch, incType, incAccId, incSortBy, incSortDir); }}
          />
        </TabToolbar>
        <TableContainer sx={{ overflowX: "auto" }}>
          <Table size="small" sx={{ minWidth: 700 }}>
            <TableHead>
              <TableRow>
                <SortableHead label="Data" field="date" sortBy={incSortBy} sortDir={incSortDir} onSort={handleIncSort} />
                <SortableHead label="Descrizione" field="name" sortBy={incSortBy} sortDir={incSortDir} onSort={handleIncSort} />
                <SortableHead label="Importo" field="amount" sortBy={incSortBy} sortDir={incSortDir} onSort={handleIncSort} sx={{ textAlign: "right" }} />
                <TableCell sx={HEAD_SX}>Tipo</TableCell>
                <TableCell sx={HEAD_SX}>Conto</TableCell>
                <TableCell sx={{ ...HEAD_SX, width: 80 }} />
              </TableRow>
            </TableHead>
            <TableBody>
              {incomes.map(row => (
                <TableRow key={row.id} hover>
                  <TableCell sx={{ ...CELL_SX, color: "#6B7280" }}>{row.date}</TableCell>
                  <TableCell sx={CELL_SX}>{row.name}</TableCell>
                  <TableCell sx={{ ...CELL_SX, textAlign: "right", color: PRIMARY, fontWeight: 600 }}>
                    {fmtCurrency(row.amount)}
                  </TableCell>
                  <TableCell sx={CELL_SX}>
                    {row.income_type
                      ? <Chip label={row.income_type} size="small" sx={{ fontSize: "0.7rem", bgcolor: "#EEF2FF", color: PRIMARY, textTransform: "capitalize" }} />
                      : <span style={{ color: "#9CA3AF" }}>—</span>}
                  </TableCell>
                  <TableCell sx={{ ...CELL_SX, color: "#6B7280" }}>{row.account || "—"}</TableCell>
                  <TableCell sx={CELL_SX}>
                    <RowActions
                      onEdit={() => openEdit("income", {
                        id: row.id, name: row.name, amount: row.amount,
                        date: row.date, income_type: row.income_type ?? "",
                        account_id: row.account_id ?? "",
                      })}
                      onDelete={() => handleDelete("income", row.id)}
                    />
                  </TableCell>
                </TableRow>
              ))}
              {!loading.incomes && incomes.length === 0 && <EmptyRow colSpan={6} />}
            </TableBody>
          </Table>
        </TableContainer>
        <TablePagination
          component="div"
          count={incTotal}
          page={incPage}
          rowsPerPage={incRowsPP}
          rowsPerPageOptions={[10, 25, 50]}
          onPageChange={(_, p) => { setIncPage(p); fetchIncomes(p, incRowsPP, incStart, incEnd, incSearch, incType, incAccId, incSortBy, incSortDir); }}
          onRowsPerPageChange={e => { const rpp = parseInt(e.target.value); setIncRowsPP(rpp); setIncPage(0); fetchIncomes(0, rpp, incStart, incEnd, incSearch, incType, incAccId, incSortBy, incSortDir); }}
          labelRowsPerPage="Righe:"
          sx={{ fontSize: "0.75rem" }}
        />
      </>
    );
  }

  function renderTransfers() {
    const accName = (id: number) => accounts.find(a => a.id === id)?.name ?? "—";
    return (
      <Box>
        <TabToolbar label="Trasferimenti" onAdd={() => openAdd("transfer")} loading={loading.transfers}>
          {accounts.length < 2 && (
            <Typography variant="caption" sx={{ color: "#9CA3AF" }}>
              Servono almeno due conti per creare un trasferimento
            </Typography>
          )}
        </TabToolbar>
        <TableContainer sx={{ overflowX: "auto" }}>
          <Table size="small" sx={{ minWidth: 600 }}>
            <TableHead>
              <TableRow>
                <TableCell sx={HEAD_SX}>Data</TableCell>
                <TableCell sx={HEAD_SX}>Descrizione</TableCell>
                <TableCell sx={HEAD_SX}>Da</TableCell>
                <TableCell sx={HEAD_SX}>A</TableCell>
                <TableCell sx={{ ...HEAD_SX, textAlign: "right" }}>Importo</TableCell>
              </TableRow>
            </TableHead>
            <TableBody>
              {transfers.map(row => (
                <TableRow key={row.id} hover>
                  <TableCell sx={{ ...CELL_SX, color: "#6B7280" }}>{row.date}</TableCell>
                  <TableCell sx={CELL_SX}>{row.name}</TableCell>
                  <TableCell sx={{ ...CELL_SX, color: "#6B7280" }}>{accName(row.from_account_id)}</TableCell>
                  <TableCell sx={{ ...CELL_SX, color: "#6B7280" }}>{accName(row.to_account_id)}</TableCell>
                  <TableCell sx={{ ...CELL_SX, textAlign: "right", color: PRIMARY, fontWeight: 600 }}>
                    {fmtCurrency(row.amount)}
                  </TableCell>
                </TableRow>
              ))}
              {!loading.transfers && transfers.length === 0 && <EmptyRow colSpan={5} />}
            </TableBody>
          </Table>
        </TableContainer>
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
          <InputLabel>Tipo entrata</InputLabel>
          <Select label="Tipo entrata" value={data.income_type ?? ""}
            onChange={e => setField("income_type", e.target.value)}>
            <MenuItem value=""><em>Nessuno</em></MenuItem>
            {INCOME_TYPES.map(t => <MenuItem key={t} value={t} sx={{ textTransform: "capitalize" }}>{t}</MenuItem>)}
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
    account: "Conto", category: "Categoria", subscription: "Abbonamento",
    expense: "Spesa", income: "Entrata", transfer: "Trasferimento",
  };

  // ---------------------------------------------------------------------------
  // Render
  // ---------------------------------------------------------------------------

  return (
    <Box sx={{ p: { xs: 1.5, sm: 3 }, width: "100%", maxWidth: 1400, mx: "auto", overflowX: "hidden" }}>
      {/* Header */}
      <Box sx={{ mb: 3 }}>
        <Typography variant="h5" sx={{ fontWeight: 700, color: PRIMARY, mb: 0.5 }}>
          Il mio spazio
        </Typography>
        <Typography variant="body2" sx={{ color: "#6B7280" }}>
          Gestisci conti, categorie, abbonamenti, spese ed entrate
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
      <Card sx={{ border: `1px solid ${BORDER}`, boxShadow: "0 1px 4px rgba(0,0,0,0.06)", borderRadius: 2, overflow: "hidden" }}>
        <Tabs
          value={tab}
          onChange={(_, v) => setTab(v)}
          variant="scrollable"
          scrollButtons="auto"
          allowScrollButtonsMobile
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
      <Dialog open={dialog.open} onClose={closeDialog} maxWidth="xs" fullWidth>
        <DialogTitle sx={{ fontWeight: 700, fontSize: "1rem", color: PRIMARY }}>
          {dialog.mode === "add" ? "Aggiungi" : "Modifica"} {ENTITY_LABELS[dialog.entity]}
        </DialogTitle>
        <DialogContent sx={{ pt: 0 }}>
          {renderDialogFields()}
        </DialogContent>
        <DialogActions sx={{ px: 3, pb: 2 }}>
          <Button onClick={closeDialog} sx={{ color: "#6B7280", textTransform: "none" }}>
            Annulla
          </Button>
          <Button
            variant="contained"
            onClick={handleSave}
            sx={{ bgcolor: PRIMARY, textTransform: "none", fontWeight: 600, "&:hover": { bgcolor: "#142959" } }}
          >
            {dialog.mode === "add" ? "Aggiungi" : "Salva"}
          </Button>
        </DialogActions>
      </Dialog>

      {/* Snackbar */}
      <Snackbar
        open={snack.open}
        autoHideDuration={3000}
        onClose={() => setSnack(s => ({ ...s, open: false }))}
        anchorOrigin={{ vertical: "bottom", horizontal: "center" }}
      >
        <Alert severity={snack.severity} sx={{ width: "100%" }} onClose={() => setSnack(s => ({ ...s, open: false }))}>
          {snack.msg}
        </Alert>
      </Snackbar>
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
      <Typography variant="subtitle2" sx={{ fontWeight: 700, color: "#374151", flexGrow: 1 }}>
        {label}
      </Typography>
      {children}
      {loading && <CircularProgress size={16} sx={{ color: "#9CA3AF" }} />}
      <Button
        variant="contained"
        size="small"
        startIcon={<Plus size={14} />}
        onClick={onAdd}
        sx={{
          bgcolor: PRIMARY, textTransform: "none", fontWeight: 600, fontSize: "0.8rem",
          px: 1.5, py: 0.5, "&:hover": { bgcolor: "#142959" },
        }}
      >
        Aggiungi
      </Button>
    </Box>
  );
}

function RowActions({ onEdit, onDelete }: { onEdit: () => void; onDelete: () => void }) {
  return (
    <Box sx={{ display: "flex", gap: 0.5, justifyContent: "flex-end" }}>
      <Tooltip title="Modifica">
        <IconButton size="small" onClick={onEdit} sx={{ color: "#6B7280", "&:hover": { color: PRIMARY } }}>
          <Pencil size={14} />
        </IconButton>
      </Tooltip>
      <Tooltip title="Elimina">
        <IconButton size="small" onClick={onDelete} sx={{ color: "#6B7280", "&:hover": { color: "#EF4444" } }}>
          <Trash2 size={14} />
        </IconButton>
      </Tooltip>
    </Box>
  );
}

function EmptyRow({ colSpan }: { colSpan: number }) {
  return (
    <TableRow>
      <TableCell colSpan={colSpan} sx={{ textAlign: "center", py: 4, color: "#9CA3AF", fontSize: "0.85rem" }}>
        Nessun elemento trovato
      </TableCell>
    </TableRow>
  );
}

function DateRangeFilter({
  start, end, onStart, onEnd,
}: { start: string; end: string; onStart: (v: string) => void; onEnd: (v: string) => void }) {
  return (
    <Box sx={{ display: "flex", gap: 1, alignItems: "center" }}>
      <TextField
        size="small" type="date" label="Dal" value={start}
        slotProps={{ inputLabel: { shrink: true } }}
        onChange={e => onStart(e.target.value)}
        sx={{ "& .MuiInputBase-input": { fontSize: "0.75rem" }, width: 140 }}
      />
      <TextField
        size="small" type="date" label="Al" value={end}
        slotProps={{ inputLabel: { shrink: true } }}
        onChange={e => onEnd(e.target.value)}
        sx={{ "& .MuiInputBase-input": { fontSize: "0.75rem" }, width: 140 }}
      />
    </Box>
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

function SortableHead({ label, field, sortBy, sortDir, onSort, sx: sxProp }: {
  label: string; field: string;
  sortBy: string; sortDir: "asc" | "desc";
  onSort: (field: string) => void;
  sx?: object;
}) {
  return (
    <TableCell sx={{ ...HEAD_SX, ...sxProp }}>
      <TableSortLabel
        active={sortBy === field}
        direction={sortBy === field ? sortDir : "asc"}
        onClick={() => onSort(field)}
        sx={{ fontSize: "inherit", fontWeight: "inherit", color: "inherit", "&.Mui-active": { color: PRIMARY } }}
      >
        {label}
      </TableSortLabel>
    </TableCell>
  );
}
