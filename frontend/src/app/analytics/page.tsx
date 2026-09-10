"use client";

import { useEffect, useState, useCallback, type ReactNode } from "react";
import {
  Box, Button, Card, CardContent, CardHeader, Tab, Tabs,
  Typography, Slider, Chip, Select, MenuItem, FormControl,
  InputLabel, Table, TableBody, TableCell, TableContainer, TableHead,
  TableRow, TablePagination, LinearProgress, TextField, ToggleButton, ToggleButtonGroup,
} from "@mui/material";
import {
  BarChart, Bar, PieChart, Pie, Cell, XAxis, YAxis, Tooltip,
  ResponsiveContainer, Legend, Area, LineChart, Line,
  CartesianGrid, ComposedChart,
} from "recharts";
import { formatDateIt } from "@/lib/date";
import SavingsGoalsProgress from "@/components/SavingsGoalsProgress";
import { TrendingUp, CreditCard, Wallet, Target, Lock } from "lucide-react";
import AnalyticsExperience from "./components/AnalyticsExperience";
import AdvancedCharts from "./components/AdvancedCharts";
import InfoButton from "../../components/InfoButton";
import { buildIncomeBreakdown, type IncomeTransaction } from "./advancedViewModels";
import { apiFetch } from "@/lib/api";
import ErrorBanner from "@/components/feedback/ErrorBanner";
import PageLoader from "@/components/feedback/PageLoader";

// ---------------------------------------------------------------------------
// Tipi
// ---------------------------------------------------------------------------

interface SavingsEntry { month: string; income: number; expenses: number; net: number; period_key?: string; period_label?: string; is_partial?: boolean; months_included?: number }
interface AccountMonthEntry { month: string; account: string; amount: number; period_key?: string; period_label?: string; is_partial?: boolean; months_included?: number }
interface CategoryEntry { month: string; name: string; amount: number; budget?: number; period_key?: string; period_label?: string; is_partial?: boolean; months_included?: number }
interface CategoryAvg { name: string; avg: number }
interface IncomeEntry { month: string; total: number; period_key?: string; period_label?: string; is_partial?: boolean; months_included?: number }
interface AccountBalance { name: string; balance: number }

interface OverviewData { savings: SavingsEntry[]; totals_by_account: AccountMonthEntry[]; plan_type: string }
interface CategoriesData { by_category: CategoryEntry[]; averages: CategoryAvg[]; plan_type: string }
interface IncomeData { monthly: IncomeEntry[]; plan_type: string }
interface IncomeBreakdownData { incomes: IncomeTransaction[]; total: number }
interface WealthData { accounts: AccountBalance[]; plan_type: string }

interface CapitalTrendEntry { month: string; total: number; period_key?: string; period_label?: string; is_partial?: boolean; months_included?: number; [key: string]: string | number | boolean | undefined }
interface CapitalTrendData { capital_trend: CapitalTrendEntry[]; plan_type: string; accounts?: string[] }

interface TransactionEntry {
  id: number; date: string; name: string; amount: number;
  category: string; account: string;
}
interface TransactionsData {
  transactions: TransactionEntry[];
  total: number; total_amount: number; offset: number; limit: number;
  plan_type: string;
}

interface TopMerchant { name: string; total: number; count: number; category: string; cluster_id?: number | null; category_id?: number | null }
interface TopMerchantsData { merchants: TopMerchant[]; plan_type: string; grouped?: boolean }

interface BudgetStatusEntry { category: string; budget: number; spent: number; remaining: number; percentage: number }
interface BudgetStatusData { budget_status: BudgetStatusEntry[]; month: string; total_income: number; total_spent: number; plan_type: string; error?: string }

interface SavingsRateEntry { month: string; income: number; expenses: number; savings: number; rate: number }
interface SavingsRateData { savings_rate: SavingsRateEntry[]; plan_type: string; error?: string }

interface MonthComparisonEntry { category: string; current_month: number; last_month: number; avg_3m: number; change_pct: number }
interface MonthComparisonData { comparisons: MonthComparisonEntry[]; plan_type: string; error?: string }

// ---------------------------------------------------------------------------
// Colori
// ---------------------------------------------------------------------------

// Palette categoriale a 8 tinte, ordine fisso validato CVD-safe su sfondo
// #1C363D (skill dataviz — scripts/validate_palette.js). Non riordinare:
// l'ordine è il meccanismo di sicurezza CVD, non un dettaglio estetico.
const PALETTE = ["#3987e5", "#d95926", "#199e70", "#c98500", "#d55181", "#008300", "#9085e9", "#e66767"];

const INCOME_COLOR = "#16A34A";
const EXPENSE_COLOR = "#E66767";
const NET_COLOR = "#5FC4CB";
const SAVINGS_COLOR = "#B0B5B9";

const TOOLTIP_STYLE = {
  background: "#1C363D",
  border: "1px solid rgba(176,181,185,0.25)",
  borderRadius: 8,
  color: "#E9F1EA",
  fontSize: 12,
};

const TICK_STYLE = { fontSize: 11, fill: "#B0B5B9" };
const LEGEND_STYLE = { color: "#B0B5B9", fontSize: 12 };

// ---------------------------------------------------------------------------
// Fetch helper
// ---------------------------------------------------------------------------

type TelegramWebApp = {
  initData?: string;
  ready: () => void;
  expand: () => void;
};

type TelegramWindow = Window & {
  Telegram?: {
    WebApp?: TelegramWebApp;
  };
};

// ---------------------------------------------------------------------------
// Aggregazioni lato client
// ---------------------------------------------------------------------------

function pivotByAccount(rows: AccountMonthEntry[]): { month: string;[key: string]: string | number }[] {
  const map = new Map<string, Record<string, number>>();
  for (const r of rows) {
    if (!map.has(r.month)) map.set(r.month, {});
    map.get(r.month)![r.account] = (map.get(r.month)![r.account] ?? 0) + r.amount;
  }
  return Array.from(map.entries()).map(([month, vals]) => ({ month, ...vals }));
}

function uniqueAccounts(rows: AccountMonthEntry[]): string[] {
  return [...new Set(rows.map((r) => r.account))];
}

function pivotTopCategories(rows: CategoryEntry[]): {
  data: { month: string;[key: string]: string | number }[];
  cats: string[];
} {
  const totals: Record<string, number> = {};
  for (const r of rows) totals[r.name] = (totals[r.name] ?? 0) + r.amount;
  const top5 = Object.entries(totals).sort((a, b) => b[1] - a[1]).slice(0, 5).map(([n]) => n);

  const map = new Map<string, Record<string, number>>();
  for (const r of rows) {
    if (!top5.includes(r.name)) continue;
    if (!map.has(r.month)) map.set(r.month, {});
    map.get(r.month)![r.name] = r.amount;
  }
  const data = Array.from(map.entries()).map(([month, vals]) => ({ month, ...vals }));
  return { data, cats: top5 };
}

// ---------------------------------------------------------------------------
// Slider periodo
// ---------------------------------------------------------------------------

function PeriodSlider({ value, onChange, maxMonths, actualMonths }: {
  value: number;
  onChange: (v: number) => void;
  maxMonths: number;
  actualMonths?: number;
}) {
  const marks = Array.from({ length: maxMonths }, (_, i) => {
    const val = i + 1;
    const showLabel = val <= 12 || val === maxMonths || val % 3 === 0;
    return { value: val, label: showLabel ? `${val}` : "" };
  });
  const showActual = actualMonths !== undefined && actualMonths < value;
  return (
    <Box sx={{ px: 2, mb: 3 }} data-tour="analytics-period">
      <Typography variant="body2" color="text.secondary" mb={1}>
        Storico: <strong>ultimi {value} {value === 1 ? "mese" : "mesi"}</strong>
        {showActual && (
          <Typography component="span" variant="body2" color="text.disabled" sx={{ ml: 1 }}>
            ({actualMonths} {actualMonths === 1 ? "mese trovato" : "mesi trovati"})
          </Typography>
        )}
      </Typography>
      <Slider
        aria-label="Numero di mesi nello storico"
        value={value}
        min={1} max={maxMonths} step={1}
        marks={marks}
        onChange={(_, v) => onChange(v as number)}
        sx={{ color: "primary.main" }}
      />
    </Box>
  );
}

// ---------------------------------------------------------------------------
// PremiumGate — blur per utenti Free
// ---------------------------------------------------------------------------

function PremiumGate({ isPro, children, featureName }: { isPro: boolean; children: ReactNode; featureName: string }) {
  if (isPro) return <>{children}</>;
  return (
    <Card sx={{ mb: 2, borderRadius: 2, position: "relative", overflow: "hidden" }}>
      <Box aria-hidden="true" sx={{ filter: "blur(6px)", opacity: 0.35, pointerEvents: "none", userSelect: "none" }}>
        {children}
      </Box>
      <Box sx={{
        position: "absolute", inset: 0, display: "flex",
        flexDirection: "column", alignItems: "center", justifyContent: "center",
        background: "rgba(3, 7, 18, 0.55)", zIndex: 10,
      }}>
        <Typography
          fontWeight={700}
          fontSize="1rem"
          color="text.primary"
          mb={0.5}
          sx={{ display: "flex", alignItems: "center", justifyContent: "center", gap: 0.5 }}
        >
          <Lock size={16} strokeWidth={1.5} aria-hidden="true" /> {featureName}
        </Typography>
        <Chip
          label="PRO"
          size="small"
          sx={{
            background: "var(--color-primary)",
            color: "#0a0a0a",
            fontWeight: 800,
            fontSize: "0.7rem",
          }}
        />
      </Box>
    </Card>
  );
}

// ---------------------------------------------------------------------------
// Componenti grafici
// ---------------------------------------------------------------------------

function ChartCard({ title, children, badge }: { title: string; children: ReactNode; badge?: ReactNode }) {
  return (
    <Card sx={{ mb: 2, borderRadius: 2 }}>
      <CardHeader
        title={badge ? <Box sx={{ display: "flex", alignItems: "center", gap: 1 }}>{title}{badge}</Box> : title}
        titleTypographyProps={{ variant: "subtitle2", fontWeight: 500 }}
        sx={{ pb: 1 }}
      />
      <CardContent sx={{ pt: 0, pb: "8px !important" }}>
        <Box sx={{ width: "100%", height: { xs: 280, sm: 260 }, minWidth: 0 }}>
          {children}
        </Box>
      </CardContent>
    </Card>
  );
}

function SavingsChart({ data }: { data: SavingsEntry[] }) {
  return (
    <ChartCard title="Risparmio mensile">
      <ResponsiveContainer width="100%" height="100%" minWidth={0}>
        <BarChart data={data} barCategoryGap="15%" maxBarSize={60} accessibilityLayer={false}>
          <XAxis dataKey="month" tick={TICK_STYLE} />
          <YAxis tick={TICK_STYLE} tickFormatter={(v) => `€${v}`} />
          <Tooltip cursor={false} formatter={(v: unknown) => `€${((v as number) ?? 0).toFixed(2)}`} contentStyle={TOOLTIP_STYLE} />
          <Legend wrapperStyle={LEGEND_STYLE} />
          <Bar activeBar={false} dataKey="income" name="Entrate" fill={INCOME_COLOR} radius={[4, 4, 0, 0]}  />
          <Bar activeBar={false} dataKey="expenses" name="Uscite" fill={EXPENSE_COLOR} radius={[4, 4, 0, 0]}  />
          <Bar activeBar={false} dataKey="net" name="Netto" fill={NET_COLOR} radius={[4, 4, 0, 0]}  />
        </BarChart>
      </ResponsiveContainer>
    </ChartCard>
  );
}

function CapitalTrendChart({ data, isPro }: { data: CapitalTrendData; isPro: boolean }) {
  // Colori per linee account
  const accPalette = ["#3987e5", "#d95926", "#199e70", "#c98500", "#d55181", "#9085e9"];

  // Costruisci le linee basandoti sull'elenco accounts ritornato dal backend
  const accountLines = isPro && data.accounts
    ? data.accounts.map((accountName, i) => (
        <Line
          activeDot={false}
          key={`acc-line-${i}-${accountName}`}
          type="monotone"
          dataKey={accountName}
          name={accountName}
          stroke={accPalette[i % accPalette.length]}
          strokeWidth={1.5}
          strokeDasharray="5 5"
          dot={{ r: 3 }}
        />
      ))
    : null;

  return (
    <ChartCard title="Andamento Capitale">
      <ResponsiveContainer width="100%" height="100%" minWidth={0}>
        <ComposedChart data={data.capital_trend} accessibilityLayer={false}>
          <defs>
            <linearGradient id="capitalGradient" x1="0" y1="0" x2="0" y2="1">
              <stop offset="5%" stopColor="#5FC4CB" stopOpacity={0.25} />
              <stop offset="95%" stopColor="#5FC4CB" stopOpacity={0.03} />
            </linearGradient>
          </defs>
          <CartesianGrid strokeDasharray="3 3" stroke="rgba(176,181,185,0.25)" />
          <XAxis dataKey="month" tick={TICK_STYLE} />
          <YAxis tick={TICK_STYLE} tickFormatter={(v) => `€${v}`} />
          <Tooltip cursor={false} formatter={(v: unknown) => `€${((v as number) ?? 0).toFixed(2)}`} contentStyle={TOOLTIP_STYLE} />
          <Legend wrapperStyle={LEGEND_STYLE} />
          <Area activeDot={false} type="monotone" dataKey="total" name="Totale" fill="url(#capitalGradient)" stroke="#5FC4CB" strokeWidth={2} />
          {accountLines}
        </ComposedChart>
      </ResponsiveContainer>
    </ChartCard>
  );
}

function CategoryTrendChart({
  rows, categories, isPro, initialCategory,
}: {
  rows: CategoryEntry[];
  categories: string[];
  isPro: boolean;
  initialCategory: string | null;
}) {
  // Categoria con spesa totale più alta (usata per utenti Free)
  const topCategory = (() => {
    const totals: Record<string, number> = {};
    for (const r of rows) totals[r.name] = (totals[r.name] ?? 0) + r.amount;
    return Object.entries(totals).sort((a, b) => b[1] - a[1])[0]?.[0] ?? categories[0];
  })();

  const [selectedCats, setSelectedCats] = useState<string[]>(
    isPro
      ? (initialCategory && categories.includes(initialCategory) ? [initialCategory] : categories)
      : (topCategory ? [topCategory] : [])
  );

  // Pivot: mese -> { cat: amount }
  const pivot = new Map<string, Record<string, number>>();
  for (const r of rows) {
    if (!selectedCats.includes(r.name)) continue;
    if (!pivot.has(r.month)) pivot.set(r.month, {});
    pivot.get(r.month)![r.name] = (pivot.get(r.month)![r.name] ?? 0) + r.amount;
  }
  const data = Array.from(pivot.entries())
    .map(([month, vals]) => ({ month, ...vals }))
    .sort((a, b) => a.month.localeCompare(b.month));

  return (
    <Card sx={{ mb: 2, borderRadius: 2 }}>
      <CardHeader
        title={
          <Box sx={{ display: "flex", alignItems: "center", gap: 2, flexWrap: "wrap" }}>
            <Typography variant="subtitle2" fontWeight={500}>Andamento per Categoria</Typography>
            {isPro ? (
              <FormControl size="small" sx={{ minWidth: 160, maxWidth: "100%", width: { xs: "100%", sm: "auto" } }}>
                <InputLabel sx={{ fontSize: "0.75rem" }}>Categorie</InputLabel>
                <Select
                  multiple
                  value={selectedCats}
                  onChange={(e) => setSelectedCats(e.target.value as string[])}
                  label="Categorie"
                  sx={{ fontSize: "0.75rem" }}
                  renderValue={(s) => {
                    const arr = s as string[];
                    return arr.length > 2 ? `${arr.length} categorie selezionate` : arr.join(", ");
                  }}
                  MenuProps={{ PaperProps: { sx: { maxHeight: 320 } } }}
                >
                  {categories.map((c) => (
                    <MenuItem key={c} value={c} sx={{ fontSize: "0.75rem" }}>{c}</MenuItem>
                  ))}
                </Select>
              </FormControl>
            ) : (
              <Chip
                label="PRO: vedi tutte le categorie"
                size="small"
                sx={{
                  background: "var(--color-primary)",
                  color: "#0a0a0a",
                  fontWeight: 700,
                  fontSize: "0.65rem",
                  cursor: "default",
                }}
              />
            )}
          </Box>
        }
        sx={{ pb: 1 }}
      />
      <CardContent sx={{ pt: 0, pb: "8px !important" }}>
        <Box sx={{ width: "100%", height: { xs: 220, sm: 280 }, minWidth: 0 }}>
        <ResponsiveContainer width="100%" height="100%" minWidth={0}>
          <LineChart data={data} accessibilityLayer={false}>
            <CartesianGrid strokeDasharray="3 3" stroke="rgba(176,181,185,0.25)" />
            <XAxis dataKey="month" tick={TICK_STYLE} />
            <YAxis tick={TICK_STYLE} tickFormatter={(v) => `€${v}`} />
            <Tooltip cursor={false} formatter={(v: unknown) => `€${((v as number) ?? 0).toFixed(2)}`} contentStyle={TOOLTIP_STYLE} />
            <Legend wrapperStyle={LEGEND_STYLE} />
            {selectedCats.map((cat, i) => (
              <Line
                activeDot={false}
                key={cat}
                type="monotone"
                dataKey={cat}
                name={cat}
                stroke={PALETTE[i % PALETTE.length]}
                strokeWidth={2}
                dot={{ r: 4 }}
              />
            ))}
          </LineChart>
        </ResponsiveContainer>
        </Box>
      </CardContent>
    </Card>
  );
}

function TransactionsTable({ data, isPro, initData }: { data: TransactionsData; isPro: boolean; initData: string | null }) {
  const [page, setPage] = useState(0);
  const [rowsPerPage, setRowsPerPage] = useState(25);
  const [categoryFilter, setCategoryFilter] = useState("");
  const [accountFilter, setAccountFilter] = useState("");
  const [startDate, setStartDate] = useState("");
  const [endDate, setEndDate] = useState("");
  const [txData, setTxData] = useState<TransactionsData>(data);

  const load = useCallback(async () => {
    const params: Record<string, string> = { limit: String(rowsPerPage), offset: String(page * rowsPerPage) };
    if (isPro && categoryFilter) params.category = categoryFilter;
    if (isPro && accountFilter) params.account = accountFilter;
    if (isPro && startDate) params.start = startDate;
    if (isPro && endDate) params.end = endDate;
    try {
      const d = await apiFetch<TransactionsData>("/api/analytics/transactions", { params });
      setTxData(d);
    } catch (e) {
      console.error("Error loading transactions:", e);
    }
  }, [page, rowsPerPage, categoryFilter, accountFilter, startDate, endDate, isPro]);

  useEffect(() => {
    const timer = window.setTimeout(() => {
      void load();
    }, 0);
    return () => window.clearTimeout(timer);
  }, [load]);

  // Categorie uniche
  const categories = [...new Set(txData.transactions.map((t) => t.category))];
  const accounts = [...new Set(txData.transactions.map((t) => t.account))];

  return (
    <Card sx={{ mb: 2, borderRadius: 2 }}>
      <CardHeader
        title="Operazioni"
        titleTypographyProps={{ variant: "subtitle2", fontWeight: 500 }}
        action={
          <Typography variant="body2" color="text.secondary">
            {txData.total} tx (€{txData.total_amount.toFixed(2)})
          </Typography>
        }
        sx={{ pb: 0 }}
      />
      <CardContent sx={{ pt: 1 }}>
        {isPro && (
          <Box sx={{ display: "flex", gap: 1, mb: 2, flexWrap: "wrap" }}>
            <TextField
              label="Da"
              type="date"
              size="small"
              value={startDate}
              onChange={(e) => setStartDate(e.target.value)}
              InputLabelProps={{ shrink: true, sx: { fontSize: "0.75rem" } }}
              inputProps={{ sx: { fontSize: "0.75rem" } }}
              sx={{ minWidth: 140 }}
            />
            <TextField
              label="A"
              type="date"
              size="small"
              value={endDate}
              onChange={(e) => setEndDate(e.target.value)}
              InputLabelProps={{ shrink: true, sx: { fontSize: "0.75rem" } }}
              inputProps={{ sx: { fontSize: "0.75rem" } }}
              sx={{ minWidth: 140 }}
            />
            <FormControl size="small" sx={{ minWidth: 120 }}>
              <InputLabel sx={{ fontSize: "0.75rem" }}>Categoria</InputLabel>
              <Select value={categoryFilter} onChange={(e) => setCategoryFilter(e.target.value)} label="Categoria" sx={{ fontSize: "0.75rem" }}>
                <MenuItem value="" sx={{ fontSize: "0.75rem" }}>Tutte</MenuItem>
                {categories.map((c) => (
                  <MenuItem key={c} value={c} sx={{ fontSize: "0.75rem" }}>{c}</MenuItem>
                ))}
              </Select>
            </FormControl>
            <FormControl size="small" sx={{ minWidth: 120 }}>
              <InputLabel sx={{ fontSize: "0.75rem" }}>Conto</InputLabel>
              <Select value={accountFilter} onChange={(e) => setAccountFilter(e.target.value)} label="Conto" sx={{ fontSize: "0.75rem" }}>
                <MenuItem value="" sx={{ fontSize: "0.75rem" }}>Tutti</MenuItem>
                {accounts.map((a) => (
                  <MenuItem key={a} value={a} sx={{ fontSize: "0.75rem" }}>{a}</MenuItem>
                ))}
              </Select>
            </FormControl>
          </Box>
        )}
        <TableContainer>
          <Table size="small">
            <TableHead>
              <TableRow>
                <TableCell sx={{ fontSize: "0.75rem", fontWeight: 500 }}>Data</TableCell>
                <TableCell sx={{ fontSize: "0.75rem", fontWeight: 500 }}>Nome</TableCell>
                <TableCell sx={{ fontSize: "0.75rem", fontWeight: 500 }} align="right">Importo</TableCell>
                <TableCell sx={{ fontSize: "0.75rem", fontWeight: 500 }}>Categoria</TableCell>
                <TableCell sx={{ fontSize: "0.75rem", fontWeight: 500 }}>Conto</TableCell>
              </TableRow>
            </TableHead>
            <TableBody>
              {txData.transactions.length === 0 && (
                <TableRow>
                  <TableCell colSpan={5} align="center" sx={{ color: "text.secondary", py: 4 }}>
                    Nessuna operazione trovata
                  </TableCell>
                </TableRow>
              )}
              {txData.transactions.map((tx) => (
                <TableRow key={tx.id} hover>
                  <TableCell sx={{ fontSize: "0.75rem" }}>{formatDateIt(tx.date)}</TableCell>
                  <TableCell sx={{ fontSize: "0.75rem" }}>{tx.name}</TableCell>
                  <TableCell align="right" sx={{ fontSize: "0.75rem", color: EXPENSE_COLOR, fontWeight: 600 }}>
                    -€{tx.amount.toFixed(2)}
                  </TableCell>
                  <TableCell sx={{ fontSize: "0.75rem" }}>{tx.category}</TableCell>
                  <TableCell sx={{ fontSize: "0.75rem" }}>{tx.account}</TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </TableContainer>
        {txData.total > rowsPerPage && (
          <TablePagination
            component="div"
            count={txData.total}
            page={page}
            onPageChange={(_, p) => setPage(p)}
            rowsPerPage={rowsPerPage}
            onRowsPerPageChange={(e) => { setRowsPerPage(parseInt(e.target.value, 10)); setPage(0); }}
            rowsPerPageOptions={[10, 25, 50]}
            sx={{ fontSize: "0.75rem" }}
          />
        )}
      </CardContent>
    </Card>
  );
}

function MonthlyByAccountChart({ rows }: { rows: AccountMonthEntry[] }) {
  const data = pivotByAccount(rows);
  const accounts = uniqueAccounts(rows);
  return (
    <ChartCard title="Spesa mensile per conto">
      <ResponsiveContainer width="100%" height="100%" minWidth={0}>
        <BarChart data={data} barCategoryGap="15%" maxBarSize={60} accessibilityLayer={false}>
          <XAxis dataKey="month" tick={TICK_STYLE} />
          <YAxis tick={TICK_STYLE} tickFormatter={(v) => `€${v}`} />
          <Tooltip cursor={false} formatter={(v: unknown) => `€${((v as number) ?? 0).toFixed(2)}`} contentStyle={TOOLTIP_STYLE} />
          <Legend wrapperStyle={LEGEND_STYLE} />
          {accounts.map((acc, i) => (
            <Bar activeBar={false} key={acc} dataKey={acc} stackId="a" fill={PALETTE[i % PALETTE.length]}  />
          ))}
        </BarChart>
      </ResponsiveContainer>
    </ChartCard>
  );
}

function CategoryPieChart({ rows }: { rows: CategoryEntry[] }) {
  const lastMonth = [...new Set(rows.map((r) => r.month))].at(-1);
  const slice = rows.filter((r) => r.month === lastMonth);
  return (
    <ChartCard title={`Spese per categoria (${lastMonth ?? "—"})`}>
      <ResponsiveContainer width="100%" height="100%" minWidth={0}>
        <PieChart accessibilityLayer={false}>
          <Pie activeShape={false} data={slice} dataKey="amount" nameKey="name" cx="50%" cy="50%"
            innerRadius={38} outerRadius={62} paddingAngle={3}>
            {slice.map((_, i) => <Cell key={i} fill={PALETTE[i % PALETTE.length]} />)}
          </Pie>
          <Tooltip cursor={false} formatter={(v: unknown) => `€${((v as number) ?? 0).toFixed(2)}`} contentStyle={TOOLTIP_STYLE} />
          <Legend iconType="circle" iconSize={10} wrapperStyle={LEGEND_STYLE} />
        </PieChart>
      </ResponsiveContainer>
    </ChartCard>
  );
}

function CategoryHistoryChart({ rows }: { rows: CategoryEntry[] }) {
  const { data, cats } = pivotTopCategories(rows);
  return (
    <ChartCard title="Top 5 categorie (storico)">
      <ResponsiveContainer width="100%" height="100%" minWidth={0}>
        <BarChart data={data} barCategoryGap="15%" maxBarSize={60} accessibilityLayer={false}>
          <XAxis dataKey="month" tick={TICK_STYLE} />
          <YAxis tick={TICK_STYLE} tickFormatter={(v) => `€${v}`} />
          <Tooltip cursor={false} formatter={(v: unknown) => `€${((v as number) ?? 0).toFixed(2)}`} contentStyle={TOOLTIP_STYLE} />
          <Legend wrapperStyle={LEGEND_STYLE} />
          {cats.map((cat, i) => (
            <Bar activeBar={false} key={cat} dataKey={cat} fill={PALETTE[i % PALETTE.length]} radius={[3, 3, 0, 0]}  />
          ))}
        </BarChart>
      </ResponsiveContainer>
    </ChartCard>
  );
}

function CategoryAvgChart({ avgs }: { avgs: CategoryAvg[] }) {
  return (
    <ChartCard title="Spesa media per categoria">
      <ResponsiveContainer width="100%" height="100%" minWidth={0}>
        <BarChart data={avgs} layout="vertical" barCategoryGap="15%" maxBarSize={40} accessibilityLayer={false}>
          <XAxis type="number" tick={TICK_STYLE} tickFormatter={(v) => `€${v}`} />
          <YAxis type="category" dataKey="name" tick={TICK_STYLE} width={90} />
          <Tooltip cursor={false} formatter={(v: unknown) => `€${((v as number) ?? 0).toFixed(2)}`} contentStyle={TOOLTIP_STYLE} />
          <Bar activeBar={false} dataKey="avg" name="Media" fill="#5FC4CB" radius={[0, 4, 4, 0]}  />
        </BarChart>
      </ResponsiveContainer>
    </ChartCard>
  );
}

function IncomeChart({ data }: { data: IncomeEntry[] }) {
  return (
    <ChartCard title="Entrate mensili">
      <ResponsiveContainer width="100%" height="100%" minWidth={0}>
        <BarChart data={data} barCategoryGap="15%" maxBarSize={60} accessibilityLayer={false}>
          <XAxis dataKey="month" tick={TICK_STYLE} />
          <YAxis tick={TICK_STYLE} tickFormatter={(v) => `€${v}`} />
          <Tooltip cursor={false} formatter={(v: unknown) => `€${((v as number) ?? 0).toFixed(2)}`} contentStyle={TOOLTIP_STYLE} />
          <Bar activeBar={false} dataKey="total" name="Entrate" fill={INCOME_COLOR} radius={[4, 4, 0, 0]}  />
        </BarChart>
      </ResponsiveContainer>
    </ChartCard>
  );
}

interface LoanSummaryEntry { id: number; status: string; residual_balance: number }

/**
 * Sottrae ai conti positivi i debiti residui dei mutui/finanziamenti attivi:
 * senza questo, "Capitale per conto" mostra solo il lordo, non il patrimonio
 * netto reale. Nessuna chiamata se l'utente non ha mai avuto un loan (evita un
 * 403 rumoroso per i piani Free/Notion, per cui il gate è lo stesso di /mutuo).
 */
function NetWorthSummary({ accounts, initData }: { accounts: AccountBalance[]; initData: string | null }) {
  const [loans, setLoans] = useState<LoanSummaryEntry[] | null>(null);

  useEffect(() => {
    let cancelled = false;
    apiFetch<{ loans: LoanSummaryEntry[] }>("/api/loans")
      .then((data) => { if (!cancelled) setLoans(data.loans || []); })
      .catch(() => { if (!cancelled) setLoans([]); });
    return () => { cancelled = true; };
  }, [initData]);

  if (!loans || loans.length === 0) return null;

  const totalAssets = accounts.filter((a) => a.balance > 0).reduce((sum, a) => sum + a.balance, 0);
  const totalDebt = loans.filter((l) => l.status === "active").reduce((sum, l) => sum + l.residual_balance, 0);
  if (totalDebt === 0) return null;
  const netWorth = totalAssets - totalDebt;
  const fmt = (n: number) => n.toLocaleString("it-IT", { style: "currency", currency: "EUR" });

  return (
    <ChartCard title="Patrimonio netto">
      <div style={{ display: "flex", flexDirection: "column", gap: 8, justifyContent: "center", height: "100%" }}>
        <div style={{ display: "flex", justifyContent: "space-between" }}>
          <span style={{ color: "#B0B5B9" }}>Capitale sui conti</span>
          <span>{fmt(totalAssets)}</span>
        </div>
        <div style={{ display: "flex", justifyContent: "space-between" }}>
          <span style={{ color: "#B0B5B9" }}>Debiti residui (mutui/finanziamenti)</span>
          <span>-{fmt(totalDebt)}</span>
        </div>
        <div style={{ display: "flex", justifyContent: "space-between", fontWeight: 600, fontSize: "1.1em", marginTop: 4 }}>
          <span>Patrimonio netto</span>
          <span>{fmt(netWorth)}</span>
        </div>
      </div>
    </ChartCard>
  );
}

function WealthPieChart({ accounts }: { accounts: AccountBalance[] }) {
  const positiveAccounts = accounts.filter(a => a.balance > 0);

  if (positiveAccounts.length === 0) {
    return (
      <ChartCard title="Capitale per conto">
        <div style={{ display: "flex", alignItems: "center", justifyContent: "center", height: "100%", color: "var(--color-text-2)" }}>
          Non è possibile visualizzare il grafico perché i saldi sono nulli o negativi
        </div>
      </ChartCard>
    );
  }

  return (
    <ChartCard title="Capitale per conto">
      <ResponsiveContainer width="100%" height="100%" minWidth={0}>
        <PieChart accessibilityLayer={false}>
          <Pie activeShape={false} data={positiveAccounts} dataKey="balance" nameKey="name" cx="50%" cy="50%"
            innerRadius={38} outerRadius={62} paddingAngle={3}>
            {positiveAccounts.map((_, i) => <Cell key={i} fill={PALETTE[i % PALETTE.length]} />)}
          </Pie>
          <Tooltip cursor={false} formatter={(v: unknown) => `€${((v as number) ?? 0).toFixed(2)}`} contentStyle={TOOLTIP_STYLE} />
          <Legend iconType="circle" iconSize={10} wrapperStyle={LEGEND_STYLE} />
        </PieChart>
      </ResponsiveContainer>
    </ChartCard>
  );
}

function BudgetGaugeList({ data }: { data: BudgetStatusData }) {
  if (data.error) {
    return (
      <ChartCard title="Stato Budget" badge={<InfoButton explanation="Stato dei budget per categoria del mese corrente. Include categorie con budget e transazioni regsitrate su Expensum nel mese corrente, esclude categorie senza budget." /> }>
        <div style={{ display: "flex", alignItems: "center", justifyContent: "center", height: "100%", color: "var(--color-text-2)" }}>
          {data.error}
        </div>
      </ChartCard>
    );
  }
  if (data.budget_status.length === 0) {
    return (
      <ChartCard title="Stato Budget" badge={<InfoButton explanation="Stato dei budget per categoria del mese corrente. Include categorie con budget e transazioni regsitrate su Expensum nel mese corrente, esclude categorie senza budget." /> }>
        <div style={{ display: "flex", alignItems: "center", justifyContent: "center", height: "100%", color: "var(--color-text-2)" }}>
          Nessun budget impostato. Imposta un budget mensile alle tue categorie.
        </div>
      </ChartCard>
    );
  }
  return (
    <Card sx={{ mb: 2, borderRadius: 2 }}>
      <CardHeader
        title={<Box sx={{ display: "flex", alignItems: "center" }}>Stato Budget: {data.month}<InfoButton explanation="Stato dei budget per categoria del mese corrente. Include categorie con budget e transazioni regsitrate su Expensum nel mese corrente, esclude categorie senza budget." /></Box>}
        titleTypographyProps={{ variant: "subtitle2", fontWeight: 500 }}
        action={
          <Typography variant="body2" color="text.secondary">
            Entrate: €{data.total_income.toFixed(2)} | Speso: €{data.total_spent.toFixed(2)}
          </Typography>
        }
        sx={{ pb: 1 }}
      />
      <CardContent sx={{ pt: 0 }}>
        {data.budget_status.map((item) => {
          // Resta sulla palette di brand ovunque tranne che per "Sforato": quello e' l'unico
          // stato che merita di rompere il brand kit con un vero colore di allarme (rosso),
          // perche' segnala un budget gia' superato. "Quasi finito" resta un colore di brand
          // (oro scuro), ma di una famiglia diversa dal blu normale e dagli altri oro usati
          // altrove nel grafico, cosi' i tre stati restano distinguibili a colpo d'occhio.
          const isOver = item.percentage >= 100;
          const isWarning = item.percentage >= 85 && item.percentage < 100;
          const barColor = isOver ? "var(--status-critical)" : isWarning ? "var(--status-warning)" : "var(--color-primary)";
          return (
            <Box key={item.category} sx={{ mb: 1.5 }}>
              <Box sx={{ display: "flex", justifyContent: "space-between", mb: 0.5 }}>
                <Typography variant="body2" fontWeight={600} component="div">
                  {item.category}
                  {isOver && <Chip label="Sforato" size="small" sx={{ ml: 1, bgcolor: "#d03b3b", color: "#fff", fontSize: "0.65rem", height: 18 }} />}
                  {isWarning && <Chip label="Quasi finito" size="small" sx={{ ml: 1, bgcolor: "var(--status-warning)", color: "#1C363D", fontSize: "0.65rem", height: 18 }} />}
                </Typography>
                <Typography variant="body2" color="text.secondary">
                  €{item.spent.toFixed(2)} / €{item.budget.toFixed(2)}
                </Typography>
              </Box>
              <LinearProgress
                variant="determinate"
                value={Math.min(item.percentage, 100)}
                sx={{
                  height: 8,
                  borderRadius: 4,
                  bgcolor: "rgba(233,241,234,0.06)",
                  "& .MuiLinearProgress-bar": { bgcolor: barColor, borderRadius: 4 },
                }}
              />
              <Typography variant="caption" color="text.secondary" sx={{ mt: 0.25, display: "block" }}>
                {item.percentage.toFixed(0)}% ({isOver ? `€${Math.abs(item.remaining).toFixed(2)} oltre` : `€${item.remaining.toFixed(2)} rimanenti`})
              </Typography>
            </Box>
          );
        })}
      </CardContent>
    </Card>
  );
}

function SavingsRateChart({ data }: { data: SavingsRateData }) {
  const [viewMode, setViewMode] = useState<"absolute" | "percentage">("absolute");

  if (data.error || data.savings_rate.length === 0) {
    return (
      <ChartCard title="Tasso di Risparmio">
        <div style={{ display: "flex", alignItems: "center", justifyContent: "center", height: "100%", color: "var(--color-text-2)" }}>
          {data.error || "Nessun dato disponibile"}
        </div>
      </ChartCard>
    );
  }
  // Calcola media
  const avgRate = data.savings_rate.reduce((sum, e) => sum + e.rate, 0) / data.savings_rate.length;

  return (
    <Card sx={{ mb: 2, borderRadius: 2 }}>
      <CardHeader
        title="Tasso di Risparmio"
        titleTypographyProps={{ variant: "subtitle2", fontWeight: 500 }}
        action={
          <Box sx={{ display: "flex", alignItems: "center", gap: 2 }}>
            <Typography variant="body2" color="text.secondary">
              Media: {avgRate.toFixed(1)}%
            </Typography>
            <ToggleButtonGroup
              size="small"
              value={viewMode}
              exclusive
              onChange={(_, newMode) => { if (newMode) setViewMode(newMode); }}
              aria-label="view mode"
              sx={{ height: 28 }}
            >
              <ToggleButton value="absolute" aria-label="absolute" sx={{ minWidth: 44, minHeight: 44, fontSize: "0.75rem" }}>
                €
              </ToggleButton>
              <ToggleButton value="percentage" aria-label="percentage" sx={{ minWidth: 44, minHeight: 44, fontSize: "0.75rem" }}>
                %
              </ToggleButton>
            </ToggleButtonGroup>
          </Box>
        }
        sx={{ pb: 1 }}
      />
      <CardContent sx={{ pt: 0, pb: "8px !important" }}>
        <Box sx={{ width: "100%", height: { xs: 280, sm: 260 }, minWidth: 0 }}>
        <ResponsiveContainer width="100%" height="100%" minWidth={0}>
          <ComposedChart data={data.savings_rate} accessibilityLayer={false}>
            <CartesianGrid strokeDasharray="3 3" stroke="rgba(176,181,185,0.25)" />
            <XAxis dataKey="month" tick={TICK_STYLE} />
            {viewMode === "percentage" ? (
              <YAxis tick={TICK_STYLE} tickFormatter={(v) => `${v}%`} />
            ) : (
              <YAxis tick={TICK_STYLE} tickFormatter={(v) => `€${v}`} />
            )}
            <Tooltip cursor={false} contentStyle={TOOLTIP_STYLE} />
            <Legend wrapperStyle={LEGEND_STYLE} />
            {viewMode === "percentage" ? (
              <Area activeDot={false} type="monotone" dataKey="rate" name="Tasso %" fill={SAVINGS_COLOR} stroke={SAVINGS_COLOR} fillOpacity={0.2} />
            ) : (
              <Bar activeBar={false} dataKey="savings" name="Risparmio €" fill={INCOME_COLOR} radius={[4, 4, 0, 0]}  />
            )}
          </ComposedChart>
        </ResponsiveContainer>
        </Box>
      </CardContent>
    </Card>
  );
}

function MonthComparisonChart({ data }: { data: MonthComparisonData }) {
  if (data.error || data.comparisons.length === 0) {
    return (
      <ChartCard title="Confronto Mensile">
        <div style={{ display: "flex", alignItems: "center", justifyContent: "center", height: "100%", color: "var(--color-text-2)" }}>
          {data.error || "Nessun dato disponibile"}
        </div>
      </ChartCard>
    );
  }
  return (
    <ChartCard title="Confronto Spese per Categoria">
      <ResponsiveContainer width="100%" height="100%" minWidth={0}>
        <BarChart data={data.comparisons} barCategoryGap="15%" maxBarSize={60} accessibilityLayer={false}>
          <XAxis dataKey="category" tick={TICK_STYLE} />
          <YAxis tick={TICK_STYLE} tickFormatter={(v) => `€${v}`} />
          <Tooltip cursor={false} formatter={(v: unknown) => `€${((v as number) ?? 0).toFixed(2)}`} contentStyle={TOOLTIP_STYLE} />
          <Legend wrapperStyle={LEGEND_STYLE} />
          <Bar activeBar={false} dataKey="avg_3m" name="Media 3m" fill="#B0B5B9" radius={[3, 3, 0, 0]}  />
          <Bar activeBar={false} dataKey="last_month" name="Mese scorso" fill="#B0B5B9" radius={[3, 3, 0, 0]}  />
          <Bar activeBar={false} dataKey="current_month" name="Questo mese" fill="#5FC4CB" radius={[3, 3, 0, 0]}  />
        </BarChart>
      </ResponsiveContainer>
    </ChartCard>
  );
}

// ---------------------------------------------------------------------------
// Pagina principale
// ---------------------------------------------------------------------------

export function LegacyAnalyticsPage() {
  const [tab, setTab] = useState(0);
  const [months, setMonths] = useState(3);
  const [granularity, setGranularity] = useState<"auto" | "monthly" | "quarterly" | "yearly">("auto");
  const [initData, setInitData] = useState<string | null>(null);
  const [isTelegram, setIsTelegram] = useState(false);
  const [mounted, setMounted] = useState(false);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  // Dati esistenti
  const [overview, setOverview] = useState<OverviewData | null>(null);
  const [categories, setCategories] = useState<CategoriesData | null>(null);
  const [income, setIncome] = useState<IncomeData | null>(null);
  const [incomeBreakdown, setIncomeBreakdown] = useState(() => buildIncomeBreakdown([]));
  const [incomeOperations, setIncomeOperations] = useState<IncomeTransaction[]>([]);
  const [wealth, setWealth] = useState<WealthData | null>(null);

  // Nuovi dati
  const [capitalTrend, setCapitalTrend] = useState<CapitalTrendData | null>(null);
  const [topMerchants, setTopMerchants] = useState<TopMerchantsData | null>(null);
  // Raggruppamento voci di spesa: preferenza persistita lato server (vedi
  // analytics_group_labels), letta dalla risposta di top-merchants per non
  // aggiungere una chiamata dedicata. `null` finché non è nota: il parametro `group`
  // va omesso, altrimenti sovrascriverebbe la preferenza salvata con il default.
  const [groupLabels, setGroupLabels] = useState<boolean | null>(null);
  const [budgetStatus, setBudgetStatus] = useState<BudgetStatusData | null>(null);
  const [savingsRate, setSavingsRate] = useState<SavingsRateData | null>(null);
  const [monthComparison, setMonthComparison] = useState<MonthComparisonData | null>(null);
  const [planType, setPlanType] = useState<string>("free");
  const [actualMonths, setActualMonths] = useState<number | undefined>(undefined);
  const isPro = planType === "pro";

  // Max months slider
  const maxMonths = isPro ? 24 : 6;
  const effectiveGranularity = granularity === "auto"
    ? (months <= 12 ? "monthly" : "quarterly")
    : granularity;

  // Rileva contesto Telegram al mount
  useEffect(() => {
    const tg = (window as TelegramWindow).Telegram?.WebApp;
    const id = tg?.initData ?? "";
    const reallyInTelegram = Boolean(tg) && id.length > 0;
    if (reallyInTelegram) {
      tg!.ready();
      tg!.expand();
      setIsTelegram(true);
      setInitData(id);
    }
    setMounted(true);
  }, []);

  useEffect(() => {
    const params = new URLSearchParams(window.location.search);
    if (params.get("tab") === "expenses") setTab(1);
    if (params.get("months") === "1") setMonths(1);
  }, []);

  const loadData = useCallback(async (m: number, id: string | null, aggregation: "monthly" | "quarterly" | "yearly") => {
    setLoading(true);
    setError(null);
    try {
      const monthStr = String(m);
      // Richiedi sempre il limite Pro (10) — il backend lo capperà per utenti Free
      const today = new Date();
      const startDate = new Date(today.getFullYear(), today.getMonth() - m + 1, 1).toISOString().slice(0, 10);
      const endDate = today.toISOString().slice(0, 10);
      const [ov, cat, inc, wea, cap, mer, incomeRows] = await Promise.all([
        apiFetch<OverviewData>("/api/analytics/overview", { params: { months: monthStr, granularity: aggregation } }),
        apiFetch<CategoriesData>("/api/analytics/categories-expense", { params: { months: monthStr, granularity: aggregation } }),
        apiFetch<IncomeData>("/api/analytics/income", { params: { months: monthStr, granularity: aggregation } }),
        apiFetch<WealthData>("/api/analytics/wealth"),
        apiFetch<CapitalTrendData>("/api/analytics/capital-trend", { params: { months: monthStr, granularity: aggregation } }),
        apiFetch<TopMerchantsData>("/api/analytics/top-merchants", { params: { months: monthStr, limit: "10", granularity: aggregation, ...(groupLabels === null ? {} : { group: groupLabels ? "1" : "0" }) } }),
        apiFetch<IncomeBreakdownData>("/api/space/incomes", { params: { limit: "500", offset: "0", start: startDate, end: endDate } }),
      ]);
      setOverview(ov);
      setCategories(cat);
      setIncome(inc);
      setWealth(wea);
      setCapitalTrend(cap);
      setTopMerchants(mer);
      if (mer.grouped !== undefined) setGroupLabels(mer.grouped);
      setIncomeBreakdown(buildIncomeBreakdown(incomeRows.incomes ?? []));
      setIncomeOperations(incomeRows.incomes ?? []);

      // Mesi effettivi = mesi distinti presenti nei dati overview
      const distinctMonths = new Set([
        ...ov.savings.map((s) => s.month),
        ...ov.totals_by_account.map((a) => a.month),
      ]);
      setActualMonths(distinctMonths.size > 0 ? distinctMonths.size : undefined);

      // Determina plan_type dalla prima risposta che lo contiene
      const pt = ov.plan_type || cat.plan_type || inc.plan_type || wea.plan_type || "free";
      setPlanType(pt);

      // Carica dati Pro-only se l'utente è Pro
      if (pt === "pro") {
        const [bud, sr, mc] = await Promise.all([
          apiFetch<BudgetStatusData>("/api/analytics/budget-status"),
          apiFetch<SavingsRateData>("/api/analytics/savings-rate", { params: { months: monthStr, granularity: aggregation } }),
          apiFetch<MonthComparisonData>("/api/analytics/month-comparison", { params: { granularity: aggregation } }),
        ]);
        setBudgetStatus(bud);
        setSavingsRate(sr);
        setMonthComparison(mc);
      }
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : "Errore nel caricamento dei dati");
    } finally {
      setLoading(false);
    }
  }, [groupLabels]);

  /** Salva la preferenza di raggruppamento (ottimistica) e ricarica i grafici. */
  const handleGroupedChange = useCallback(async (next: boolean) => {
    const previous = groupLabels;
    setGroupLabels(next);
    try {
      await apiFetch("/api/user/preferences", {
        method: "PUT",
        body: { analytics_group_labels: next },
      });
    } catch {
      setGroupLabels(previous);
    }
  }, [groupLabels]);

  useEffect(() => {
    if (!mounted) return;
    if (isTelegram) {
      if (!initData) {
        setError("auth_401");
        setLoading(false);
      } else {
        loadData(months, initData, effectiveGranularity);
      }
    } else {
      loadData(months, null, effectiveGranularity);
    }
  }, [isTelegram, initData, months, effectiveGranularity, loadData, mounted]);

  const handleMonthsChange = (v: number) => {
    setMonths(v);
  };

  if (!mounted) return null;

  const isNgrok = typeof window !== "undefined" && window.location.hostname.includes("ngrok-free.app");
  const showHeader = !isTelegram && !isNgrok;

  return (
    <Box sx={{
      p: { xs: 1, sm: 2, md: 3 },
      width: "100%",
      maxWidth: (isTelegram || isNgrok) ? "100%" : 960,
      mx: "auto",
      overflowX: "hidden"
    }}>
      {showHeader && (
        <>
          <Typography
            component="h1"
            variant="h5"
            fontWeight={300}
            color="primary"
            mb={1}
            sx={{ display: "flex", alignItems: "center", gap: 1 }}
          >
            Analytics
          </Typography>
          <Typography variant="body2" color="text.secondary" mb={3}>
            Analisi delle tue finanze con Moneo
          </Typography>
        </>
      )}

      <Box sx={{ display: "flex", alignItems: "end", gap: 2, flexWrap: "wrap" }}>
        <Box sx={{ flex: "1 1 260px", minWidth: 0 }}>
          <PeriodSlider value={months} onChange={handleMonthsChange} maxMonths={maxMonths} actualMonths={actualMonths} />
        </Box>
        <FormControl size="small" sx={{ minWidth: 150, mb: 3, minHeight: 44 }}>
          <InputLabel id="advanced-granularity-label">Aggregazione</InputLabel>
          <Select labelId="advanced-granularity-label" value={granularity} label="Aggregazione" onChange={(event) => setGranularity(event.target.value as typeof granularity)} sx={{ minHeight: 44 }}>
            <MenuItem value="auto">Auto</MenuItem>
            <MenuItem value="monthly">Mensile</MenuItem>
            <MenuItem value="quarterly">Trimestrale</MenuItem>
            <MenuItem value="yearly">Annuale</MenuItem>
          </Select>
        </FormControl>
      </Box>

      <Tabs
        value={tab}
        onChange={(_, v) => setTab(v)}
        sx={{ mb: 2, minHeight: 44 }}
        variant="scrollable"
        scrollButtons="auto"
        allowScrollButtonsMobile
        data-tour="analytics-tabs"
      >
        <Tab
          label={
            <Box sx={{ display: "flex", alignItems: "center", gap: 0.5 }}>
              <TrendingUp size={14} strokeWidth={1.5} aria-hidden="true" /> Panoramica
            </Box>
          }
          sx={{ fontSize: "0.75rem", minHeight: 44 }}
        />
        <Tab
          label={
            <Box sx={{ display: "flex", alignItems: "center", gap: 0.5 }}>
              <CreditCard size={14} strokeWidth={1.5} aria-hidden="true" /> Spese
            </Box>
          }
          sx={{ fontSize: "0.75rem", minHeight: 44 }}
        />
        <Tab
          label={
            <Box sx={{ display: "flex", alignItems: "center", gap: 0.5 }}>
              <Wallet size={14} strokeWidth={1.5} aria-hidden="true" /> Entrate
            </Box>
          }
          sx={{ fontSize: "0.75rem", minHeight: 44 }}
        />
        <Tab
          label={
            <Box sx={{ display: "flex", alignItems: "center", gap: 0.5 }}>
              <Target size={14} strokeWidth={1.5} aria-hidden="true" /> Budget
              {!isPro && (
                <Chip
                  label="PRO"
                  size="small"
                  sx={{
                    background: "var(--color-primary)",
                    color: "#0a0a0a",
                    fontWeight: 800,
                    fontSize: "0.6rem",
                    height: 18,
                  }}
                />
              )}
            </Box>
          }
          sx={{ fontSize: "0.75rem", minHeight: 44 }}
        />
      </Tabs>

      {loading && <PageLoader sx={{ py: 6 }} />}

      {!loading && (
        <ErrorBanner
          message={
            !error
              ? null
              : error === "auth_401"
                ? (isTelegram
                  ? "Sessione Telegram scaduta: riapri la mini-app dal bot."
                  : "Apri questa pagina dalla mini-app Telegram.")
                : error
          }
        />
      )}

      {!loading && !error && overview && categories && income && wealth && capitalTrend && topMerchants && (
        <>
          {/* Tab 0: Panoramica */}
          {tab === 0 && (
            <>
              <AdvancedCharts
                mode="overview"
                savings={overview.savings.map((row) => ({ ...row, savings: row.net }))}
                capitalTrend={capitalTrend.capital_trend}
                accountRows={overview.totals_by_account}
                savingsRate={isPro && savingsRate && savingsRate.savings_rate.length > 0 ? savingsRate.savings_rate : undefined}
                categories={[]}
                merchants={[]}
                accounts={wealth.accounts}
                comparisons={[]}
              />
              {!isPro && (
                <PremiumGate isPro={false} featureName="Tasso di Risparmio">
                  <Box sx={{ minHeight: 100, display: "grid", placeItems: "center" }}>Tasso di Risparmio disponibile per Pro</Box>
                </PremiumGate>
              )}
            </>
          )}

          {/* Tab 1: Spese */}
          {tab === 1 && (
            <>
              <AdvancedCharts
                categories={categories.by_category.map((row) => ({
                  ...row,
                  period_key: row.period_key ?? row.month,
                  period_label: row.period_label ?? row.month,
                }))}
                merchants={topMerchants.merchants}
                accounts={wealth.accounts}
                comparisons={monthComparison?.comparisons ?? []}
                months={months}
                grouped={groupLabels ?? true}
                onGroupedChange={(next) => void handleGroupedChange(next)}
                onReload={() => loadData(months, initData, effectiveGranularity)}
              />
              {!isPro && (
                <PremiumGate isPro={false} featureName="Confronto Mensile">
                  <Box sx={{ minHeight: 100, display: "grid", placeItems: "center" }}>Confronto Mensile disponibile per Pro</Box>
                </PremiumGate>
              )}
            </>
          )}

          {/* Tab 2: Entrate */}
          {tab === 2 && (
            <>
              <AdvancedCharts
                mode="income"
                income={income.monthly.map((row) => ({ ...row, income: row.total, expenses: 0, savings: row.total }))}
                categories={[]}
                merchants={[]}
                accounts={wealth.accounts}
                comparisons={[]}
                incomeCategories={incomeBreakdown.byCategory}
                incomeNature={incomeBreakdown.byNature}
                incomeOperations={incomeOperations}
              />
            </>
          )}

          {/* Tab 3: Budget (Pro) */}
          {tab === 3 && (
            <>
              {isPro && <Box><Box sx={{ display: "flex", justifyContent: "flex-end", minHeight: 44 }}><InfoButton explanation="Obiettivi di risparmio: avanzamento degli obiettivi attivi rispetto al target. Include gli obiettivi collegati e i progressi registrati; esclude obiettivi archiviati." /></Box><SavingsGoalsProgress /></Box>}
              {isPro && budgetStatus ? (
                <BudgetGaugeList data={budgetStatus} />
              ) : (
                <PremiumGate isPro={false} featureName="Stato Budget">
                  <BudgetGaugeList data={{ budget_status: [], month: "", total_income: 0, total_spent: 0, plan_type: "free", error: "Pro required" }} />
                </PremiumGate>
              )}
            </>
          )}
        </>
      )}
      <Button href="/spazio" variant="text" sx={{ minHeight: 44, mt: 1 }}>Apri Gestisci</Button>
    </Box>
  );
}

/** Punto di ingresso del redesign progressivo; la vecchia implementazione resta temporaneamente isolata sopra. */
export default function AnalyticsPage() {
  const [showAdvanced, setShowAdvanced] = useState(false);

  if (showAdvanced) {
    return (
      <>
        <Box sx={{ width: "100%", maxWidth: 960, mx: "auto", pt: 2, px: { xs: 1.5, sm: 3 } }}>
          <Button variant="text" onClick={() => setShowAdvanced(false)} sx={{ minHeight: 44 }}>
            Torna alla sintesi
          </Button>
        </Box>
        <LegacyAnalyticsPage />
      </>
    );
  }

  return <AnalyticsExperience onOpenAdvanced={() => setShowAdvanced(true)} />;
}
