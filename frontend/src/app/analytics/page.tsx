"use client";

import { useEffect, useState, useCallback, type ReactNode } from "react";
import {
  Box, Card, CardContent, CardHeader, CircularProgress, Tab, Tabs,
  Typography, Slider, Alert, Chip, Select, MenuItem, FormControl,
  InputLabel, Table, TableBody, TableCell, TableContainer, TableHead,
  TableRow, TablePagination, LinearProgress, TextField, ToggleButton, ToggleButtonGroup,
} from "@mui/material";
import {
  BarChart, Bar, PieChart, Pie, Cell, XAxis, YAxis, Tooltip,
  ResponsiveContainer, Legend, Area, LineChart, Line,
  CartesianGrid, ComposedChart,
} from "recharts";

// ---------------------------------------------------------------------------
// Tipi
// ---------------------------------------------------------------------------

interface SavingsEntry { month: string; income: number; expenses: number; net: number }
interface AccountMonthEntry { month: string; account: string; amount: number }
interface CategoryEntry { month: string; name: string; amount: number; budget?: number }
interface CategoryAvg { name: string; avg: number }
interface IncomeEntry { month: string; total: number }
interface AccountBalance { name: string; balance: number }

interface OverviewData { savings: SavingsEntry[]; totals_by_account: AccountMonthEntry[]; plan_type: string }
interface CategoriesData { by_category: CategoryEntry[]; averages: CategoryAvg[]; plan_type: string }
interface IncomeData { monthly: IncomeEntry[]; plan_type: string }
interface WealthData { accounts: AccountBalance[]; plan_type: string }

interface CapitalTrendEntry { month: string; total: number; [key: string]: string | number }
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

interface TopMerchant { name: string; total: number; count: number; category: string }
interface TopMerchantsData { merchants: TopMerchant[]; plan_type: string }

interface BudgetStatusEntry { category: string; budget: number; spent: number; remaining: number; percentage: number }
interface BudgetStatusData { budget_status: BudgetStatusEntry[]; month: string; total_income: number; total_spent: number; plan_type: string; error?: string }

interface SavingsRateEntry { month: string; income: number; expenses: number; savings: number; rate: number }
interface SavingsRateData { savings_rate: SavingsRateEntry[]; plan_type: string; error?: string }

interface MonthComparisonEntry { category: string; current_month: number; last_month: number; avg_3m: number; change_pct: number }
interface MonthComparisonData { comparisons: MonthComparisonEntry[]; plan_type: string; error?: string }

// ---------------------------------------------------------------------------
// Colori
// ---------------------------------------------------------------------------

const PALETTE = ["#1A3673", "#C5A059", "#4B6CB7", "#7C9BD6", "#A8853C", "#2B4FA8", "#D4B47A", "#6B7280"];

const INCOME_COLOR = "#1A3673";
const EXPENSE_COLOR = "#C5A059";
const NET_COLOR = "#4B6CB7";
const SAVINGS_COLOR = "#7C9BD6";

const TOOLTIP_STYLE = {
  background: "#FFFFFF",
  border: "1px solid #E5E2DC",
  borderRadius: 8,
  color: "#1A1A1A",
  fontSize: 12,
};

const TICK_STYLE = { fontSize: 11, fill: "#6B7280" };
const LEGEND_STYLE = { color: "#6B7280", fontSize: 12 };

// ---------------------------------------------------------------------------
// Fetch helper
// ---------------------------------------------------------------------------

const API_BASE = process.env.NEXT_PUBLIC_API_URL ?? "";

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

function makeHeaders(initData: string | null): HeadersInit {
  return initData ? { "X-Telegram-Init-Data": initData } : {};
}

async function fetchApi<T>(path: string, initData: string | null, extraParams: Record<string, string> = {}): Promise<T> {
  const params = new URLSearchParams(extraParams);
  const url = `${API_BASE}${path}?${params.toString()}`;
  const headers = makeHeaders(initData);
  console.log("fetchApi:", url);
  const res = await fetch(url, { headers });
  if (!res.ok) {
    console.error("fetchApi failed:", res.status, await res.text());
    if (res.status === 401) throw new Error("auth_401");
    throw new Error(`Errore API ${res.status}`);
  }
  return res.json() as Promise<T>;
}

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

function PeriodSlider({ value, onChange, maxMonths }: { value: number; onChange: (v: number) => void; maxMonths: number }) {
  const marks = Array.from({ length: maxMonths }, (_, i) => {
    const val = i + 1;
    // Mostra etichetta ogni mese fino a 12, poi ogni 3 mesi
    const showLabel = val <= 12 || val === maxMonths || val % 3 === 0;
    return { value: val, label: showLabel ? `${val}` : "" };
  });
  return (
    <Box sx={{ px: 2, mb: 3 }}>
      <Typography variant="body2" color="text.secondary" mb={1}>
        Storico: <strong>ultimi {value} {value === 1 ? "mese" : "mesi"}</strong>
      </Typography>
      <Slider
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
        <Typography fontWeight={700} fontSize="1rem" color="text.primary" mb={0.5}>
          🔒 {featureName}
        </Typography>
        <Chip
          label="PRO"
          size="small"
          sx={{
            background: "linear-gradient(135deg, #C5A059, #D4B47A)",
            color: "#ffffff",
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
        titleTypographyProps={{ variant: "subtitle2", fontWeight: 700 }}
        sx={{ pb: 1 }}
      />
      <CardContent sx={{ height: { xs: 200, sm: 260 }, pt: 0, minWidth: 0, minHeight: 0, "& .recharts-responsive-container": { minWidth: 0, minHeight: 0 } }}>{children}</CardContent>
    </Card>
  );
}

function SavingsChart({ data }: { data: SavingsEntry[] }) {
  return (
    <ChartCard title="Risparmio mensile">
      <ResponsiveContainer width="100%" height="100%">
        <BarChart data={data} barCategoryGap="15%" maxBarSize={60}>
          <XAxis dataKey="month" tick={TICK_STYLE} />
          <YAxis tick={TICK_STYLE} tickFormatter={(v) => `€${v}`} />
          <Tooltip formatter={(v: number) => `€${(v ?? 0).toFixed(2)}`} contentStyle={TOOLTIP_STYLE} />
          <Legend wrapperStyle={LEGEND_STYLE} />
          <Bar dataKey="income" name="Entrate" fill={INCOME_COLOR} radius={[4, 4, 0, 0]}  />
          <Bar dataKey="expenses" name="Uscite" fill={EXPENSE_COLOR} radius={[4, 4, 0, 0]}  />
          <Bar dataKey="net" name="Netto" fill={NET_COLOR} radius={[4, 4, 0, 0]}  />
        </BarChart>
      </ResponsiveContainer>
    </ChartCard>
  );
}

function CapitalTrendChart({ data, isPro }: { data: CapitalTrendData; isPro: boolean }) {
  // Colori per linee account
  const accPalette = ["#4B6CB7", "#7C9BD6", "#C5A059", "#1A3673", "#A8853C", "#2B4FA8"];
  
  // Costruisci le linee basandoti sull'elenco accounts ritornato dal backend
  const accountLines = isPro && data.accounts
    ? data.accounts.map((accountName, i) => (
        <Line
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
      <ResponsiveContainer width="100%" height="100%">
        <ComposedChart data={data.capital_trend}>
          <defs>
            <linearGradient id="capitalGradient" x1="0" y1="0" x2="0" y2="1">
              <stop offset="5%" stopColor="#1A3673" stopOpacity={0.25} />
              <stop offset="95%" stopColor="#1A3673" stopOpacity={0.03} />
            </linearGradient>
          </defs>
          <CartesianGrid strokeDasharray="3 3" stroke="#E5E2DC" />
          <XAxis dataKey="month" tick={TICK_STYLE} />
          <YAxis tick={TICK_STYLE} tickFormatter={(v) => `€${v}`} />
          <Tooltip formatter={(v: number) => `€${(v ?? 0).toFixed(2)}`} contentStyle={TOOLTIP_STYLE} />
          <Legend wrapperStyle={LEGEND_STYLE} />
          <Area type="monotone" dataKey="total" name="Totale" fill="url(#capitalGradient)" stroke="#1A3673" strokeWidth={2} />
          {accountLines}
        </ComposedChart>
      </ResponsiveContainer>
    </ChartCard>
  );
}

function CategoryTrendChart({
  rows, categories, isPro,
}: {
  rows: CategoryEntry[];
  categories: string[];
  isPro: boolean;
}) {
  const [selectedCats, setSelectedCats] = useState<string[]>(categories.slice(0, isPro ? 3 : 1));

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
            <Typography variant="subtitle2" fontWeight={700}>Andamento per Categoria</Typography>
            {isPro && (
              <FormControl size="small" sx={{ minWidth: 200 }}>
                <InputLabel sx={{ fontSize: "0.75rem" }}>Categorie</InputLabel>
                <Select
                  multiple
                  value={selectedCats}
                  onChange={(e) => setSelectedCats(e.target.value as string[])}
                  label="Categorie"
                  sx={{ fontSize: "0.75rem" }}
                  renderValue={(s) => (s as string[]).join(", ")}
                >
                  {categories.map((c) => (
                    <MenuItem key={c} value={c} sx={{ fontSize: "0.75rem" }}>{c}</MenuItem>
                  ))}
                </Select>
              </FormControl>
            )}
          </Box>
        }
        sx={{ pb: 1 }}
      />
      <CardContent sx={{ height: { xs: 220, sm: 280 }, pt: 0, minWidth: 0, minHeight: 0 }}>
        <ResponsiveContainer width="100%" height="100%">
          <LineChart data={data}>
            <CartesianGrid strokeDasharray="3 3" stroke="#E5E2DC" />
            <XAxis dataKey="month" tick={TICK_STYLE} />
            <YAxis tick={TICK_STYLE} tickFormatter={(v) => `€${v}`} />
            <Tooltip formatter={(v: number) => `€${(v ?? 0).toFixed(2)}`} contentStyle={TOOLTIP_STYLE} />
            <Legend wrapperStyle={LEGEND_STYLE} />
            {selectedCats.map((cat, i) => (
              <Line
                key={cat}
                type="monotone"
                dataKey={cat}
                name={cat}
                stroke={PALETTE[i % PALETTE.length]}
                strokeWidth={2}
                dot={{ r: 4 }}
                activeDot={{ r: 6 }}
              />
            ))}
          </LineChart>
        </ResponsiveContainer>
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
      const d = await fetchApi<TransactionsData>("/api/analytics/transactions", initData, params);
      setTxData(d);
    } catch (e) {
      console.error("Error loading transactions:", e);
    }
  }, [page, rowsPerPage, categoryFilter, accountFilter, startDate, endDate, isPro, initData]);

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
        titleTypographyProps={{ variant: "subtitle2", fontWeight: 700 }}
        action={
          <Typography variant="body2" color="text.secondary">
            {txData.total} tx — €{txData.total_amount.toFixed(2)}
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
                <TableCell sx={{ fontSize: "0.75rem", fontWeight: 700 }}>Data</TableCell>
                <TableCell sx={{ fontSize: "0.75rem", fontWeight: 700 }}>Nome</TableCell>
                <TableCell sx={{ fontSize: "0.75rem", fontWeight: 700 }} align="right">Importo</TableCell>
                <TableCell sx={{ fontSize: "0.75rem", fontWeight: 700 }}>Categoria</TableCell>
                <TableCell sx={{ fontSize: "0.75rem", fontWeight: 700 }}>Conto</TableCell>
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
                  <TableCell sx={{ fontSize: "0.75rem" }}>{tx.date}</TableCell>
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
      <ResponsiveContainer width="100%" height="100%">
        <BarChart data={data} barCategoryGap="15%" maxBarSize={60}>
          <XAxis dataKey="month" tick={TICK_STYLE} />
          <YAxis tick={TICK_STYLE} tickFormatter={(v) => `€${v}`} />
          <Tooltip formatter={(v: number) => `€${(v ?? 0).toFixed(2)}`} contentStyle={TOOLTIP_STYLE} />
          <Legend wrapperStyle={LEGEND_STYLE} />
          {accounts.map((acc, i) => (
            <Bar key={acc} dataKey={acc} stackId="a" fill={PALETTE[i % PALETTE.length]}  />
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
      <ResponsiveContainer width="100%" height="100%">
        <PieChart>
          <Pie data={slice} dataKey="amount" nameKey="name" cx="50%" cy="50%"
            innerRadius={55} outerRadius={90} paddingAngle={3}>
            {slice.map((_, i) => <Cell key={i} fill={PALETTE[i % PALETTE.length]} />)}
          </Pie>
          <Tooltip formatter={(v: number) => `€${(v ?? 0).toFixed(2)}`} contentStyle={TOOLTIP_STYLE} />
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
      <ResponsiveContainer width="100%" height="100%">
        <BarChart data={data} barCategoryGap="15%" maxBarSize={60}>
          <XAxis dataKey="month" tick={TICK_STYLE} />
          <YAxis tick={TICK_STYLE} tickFormatter={(v) => `€${v}`} />
          <Tooltip formatter={(v: number) => `€${(v ?? 0).toFixed(2)}`} contentStyle={TOOLTIP_STYLE} />
          <Legend wrapperStyle={LEGEND_STYLE} />
          {cats.map((cat, i) => (
            <Bar key={cat} dataKey={cat} fill={PALETTE[i % PALETTE.length]} radius={[3, 3, 0, 0]}  />
          ))}
        </BarChart>
      </ResponsiveContainer>
    </ChartCard>
  );
}

function CategoryAvgChart({ avgs }: { avgs: CategoryAvg[] }) {
  return (
    <ChartCard title="Spesa media per categoria">
      <ResponsiveContainer width="100%" height="100%">
        <BarChart data={avgs} layout="vertical" barCategoryGap="15%" maxBarSize={40}>
          <XAxis type="number" tick={TICK_STYLE} tickFormatter={(v) => `€${v}`} />
          <YAxis type="category" dataKey="name" tick={TICK_STYLE} width={90} />
          <Tooltip formatter={(v: number) => `€${(v ?? 0).toFixed(2)}`} contentStyle={TOOLTIP_STYLE} />
          <Bar dataKey="avg" name="Media" fill="#1A3673" radius={[0, 4, 4, 0]}  />
        </BarChart>
      </ResponsiveContainer>
    </ChartCard>
  );
}

function IncomeChart({ data }: { data: IncomeEntry[] }) {
  return (
    <ChartCard title="Entrate mensili">
      <ResponsiveContainer width="100%" height="100%">
        <BarChart data={data} barCategoryGap="15%" maxBarSize={60}>
          <XAxis dataKey="month" tick={TICK_STYLE} />
          <YAxis tick={TICK_STYLE} tickFormatter={(v) => `€${v}`} />
          <Tooltip formatter={(v: number) => `€${(v ?? 0).toFixed(2)}`} contentStyle={TOOLTIP_STYLE} />
          <Bar dataKey="total" name="Entrate" fill={INCOME_COLOR} radius={[4, 4, 0, 0]}  />
        </BarChart>
      </ResponsiveContainer>
    </ChartCard>
  );
}

function WealthPieChart({ accounts }: { accounts: AccountBalance[] }) {
  const positiveAccounts = accounts.filter(a => a.balance > 0);

  if (positiveAccounts.length === 0) {
    return (
      <ChartCard title="Capitale per conto">
        <div style={{ display: "flex", alignItems: "center", justifyContent: "center", height: "100%", color: "var(--text-secondary)" }}>
          Non è possibile visualizzare il grafico perché i saldi sono nulli o negativi
        </div>
      </ChartCard>
    );
  }

  return (
    <ChartCard title="Capitale per conto">
      <ResponsiveContainer width="100%" height="100%">
        <PieChart>
          <Pie data={positiveAccounts} dataKey="balance" nameKey="name" cx="50%" cy="50%"
            innerRadius={55} outerRadius={90} paddingAngle={3}>
            {positiveAccounts.map((_, i) => <Cell key={i} fill={PALETTE[i % PALETTE.length]} />)}
          </Pie>
          <Tooltip formatter={(v: number) => `€${(v ?? 0).toFixed(2)}`} contentStyle={TOOLTIP_STYLE} />
          <Legend iconType="circle" iconSize={10} wrapperStyle={LEGEND_STYLE} />
        </PieChart>
      </ResponsiveContainer>
    </ChartCard>
  );
}

function TopMerchantsChart({ data }: { data: TopMerchantsData }) {
  if (data.merchants.length === 0) {
    return (
      <ChartCard title="Dove spendi di piu">
        <div style={{ display: "flex", alignItems: "center", justifyContent: "center", height: "100%", color: "var(--text-secondary)" }}>
          Nessun dato disponibile
        </div>
      </ChartCard>
    );
  }
  return (
    <ChartCard title="Dove spendi di piu">
      <ResponsiveContainer width="100%" height="100%">
        <BarChart data={data.merchants} layout="vertical" barCategoryGap="15%" maxBarSize={40}>
          <XAxis type="number" tick={TICK_STYLE} tickFormatter={(v) => `€${v}`} />
          <YAxis type="category" dataKey="name" tick={TICK_STYLE} width={120} />
          <Tooltip
            formatter={(v: number, _name: string, props: { payload: { count: number; category: string } }) => [`€${(v ?? 0).toFixed(2)} (x${props.payload.count})`, props.payload.category]}
            contentStyle={TOOLTIP_STYLE}
          />
          <Bar dataKey="total" name="Spesa" radius={[0, 4, 4, 0]}>
            {data.merchants.map((_, i) => (
              <Cell key={i} fill={PALETTE[i % PALETTE.length]} />
            ))}
          </Bar>
        </BarChart>
      </ResponsiveContainer>
    </ChartCard>
  );
}

function BudgetGaugeList({ data }: { data: BudgetStatusData }) {
  if (data.error) {
    return (
      <ChartCard title="Stato Budget">
        <div style={{ display: "flex", alignItems: "center", justifyContent: "center", height: "100%", color: "var(--text-secondary)" }}>
          {data.error}
        </div>
      </ChartCard>
    );
  }
  if (data.budget_status.length === 0) {
    return (
      <ChartCard title="Stato Budget">
        <div style={{ display: "flex", alignItems: "center", justifyContent: "center", height: "100%", color: "var(--text-secondary)" }}>
          Nessun budget impostato. Imposta un budget mensile alle tue categorie.
        </div>
      </ChartCard>
    );
  }
  return (
    <Card sx={{ mb: 2, borderRadius: 2 }}>
      <CardHeader
        title={`Stato Budget — ${data.month}`}
        titleTypographyProps={{ variant: "subtitle2", fontWeight: 700 }}
        action={
          <Typography variant="body2" color="text.secondary">
            Entrate: €{data.total_income.toFixed(2)} | Speso: €{data.total_spent.toFixed(2)}
          </Typography>
        }
        sx={{ pb: 1 }}
      />
      <CardContent sx={{ pt: 0 }}>
        {data.budget_status.map((item) => {
          const isOver = item.percentage >= 100;
          const isWarning = item.percentage >= 85 && item.percentage < 100;
          const barColor = isOver ? "#C5A059" : isWarning ? "#D4B47A" : "#1A3673";
          return (
            <Box key={item.category} sx={{ mb: 1.5 }}>
              <Box sx={{ display: "flex", justifyContent: "space-between", mb: 0.5 }}>
                <Typography variant="body2" fontWeight={600} component="div">
                  {item.category}
                  {isOver && <Chip label="Sforato" size="small" sx={{ ml: 1, bgcolor: "#C5A059", color: "#fff", fontSize: "0.65rem", height: 18 }} />}
                  {isWarning && <Chip label="Quasi finito" size="small" sx={{ ml: 1, bgcolor: "#D4B47A", color: "#fff", fontSize: "0.65rem", height: 18 }} />}
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
                  bgcolor: "#F0EDE8",
                  "& .MuiLinearProgress-bar": { bgcolor: barColor, borderRadius: 4 },
                }}
              />
              <Typography variant="caption" color="text.secondary" sx={{ mt: 0.25, display: "block" }}>
                {item.percentage.toFixed(0)}% — {isOver ? `€${Math.abs(item.remaining).toFixed(2)} oltre` : `€${item.remaining.toFixed(2)} rimanenti`}
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
        <div style={{ display: "flex", alignItems: "center", justifyContent: "center", height: "100%", color: "var(--text-secondary)" }}>
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
        titleTypographyProps={{ variant: "subtitle2", fontWeight: 700 }}
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
              <ToggleButton value="absolute" aria-label="absolute" sx={{ px: 1, fontSize: "0.75rem", py: 0 }}>
                €
              </ToggleButton>
              <ToggleButton value="percentage" aria-label="percentage" sx={{ px: 1, fontSize: "0.75rem", py: 0 }}>
                %
              </ToggleButton>
            </ToggleButtonGroup>
          </Box>
        }
        sx={{ pb: 1 }}
      />
      <CardContent sx={{ height: { xs: 200, sm: 260 }, pt: 0, minWidth: 0, minHeight: 0 }}>
        <ResponsiveContainer width="100%" height="100%">
          <ComposedChart data={data.savings_rate}>
            <CartesianGrid strokeDasharray="3 3" stroke="#E5E2DC" />
            <XAxis dataKey="month" tick={TICK_STYLE} />
            {viewMode === "percentage" ? (
              <YAxis tick={TICK_STYLE} tickFormatter={(v) => `${v}%`} />
            ) : (
              <YAxis tick={TICK_STYLE} tickFormatter={(v) => `€${v}`} />
            )}
            <Tooltip contentStyle={TOOLTIP_STYLE} />
            <Legend wrapperStyle={LEGEND_STYLE} />
            {viewMode === "percentage" ? (
              <Area type="monotone" dataKey="rate" name="Tasso %" fill={SAVINGS_COLOR} stroke={SAVINGS_COLOR} fillOpacity={0.2} />
            ) : (
              <Bar dataKey="savings" name="Risparmio €" fill={INCOME_COLOR} radius={[4, 4, 0, 0]}  />
            )}
          </ComposedChart>
        </ResponsiveContainer>
      </CardContent>
    </Card>
  );
}

function MonthComparisonChart({ data }: { data: MonthComparisonData }) {
  if (data.error || data.comparisons.length === 0) {
    return (
      <ChartCard title="Confronto Mensile">
        <div style={{ display: "flex", alignItems: "center", justifyContent: "center", height: "100%", color: "var(--text-secondary)" }}>
          {data.error || "Nessun dato disponibile"}
        </div>
      </ChartCard>
    );
  }
  return (
    <ChartCard title="Confronto Spese per Categoria">
      <ResponsiveContainer width="100%" height="100%">
        <BarChart data={data.comparisons} barCategoryGap="15%" maxBarSize={60}>
          <XAxis dataKey="category" tick={TICK_STYLE} />
          <YAxis tick={TICK_STYLE} tickFormatter={(v) => `€${v}`} />
          <Tooltip formatter={(v: number) => `€${(v ?? 0).toFixed(2)}`} contentStyle={TOOLTIP_STYLE} />
          <Legend wrapperStyle={LEGEND_STYLE} />
          <Bar dataKey="avg_3m" name="Media 3m" fill="#4B6CB7" radius={[3, 3, 0, 0]}  />
          <Bar dataKey="last_month" name="Mese scorso" fill="#C5A059" radius={[3, 3, 0, 0]}  />
          <Bar dataKey="current_month" name="Questo mese" fill="#1A3673" radius={[3, 3, 0, 0]}  />
        </BarChart>
      </ResponsiveContainer>
    </ChartCard>
  );
}

// ---------------------------------------------------------------------------
// Pagina principale
// ---------------------------------------------------------------------------

export default function AnalyticsPage() {
  const [tab, setTab] = useState(0);
  const [months, setMonths] = useState(3);
  const [initData, setInitData] = useState<string | null>(null);
  const [isTelegram, setIsTelegram] = useState(false);
  const [mounted, setMounted] = useState(false);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  // Dati esistenti
  const [overview, setOverview] = useState<OverviewData | null>(null);
  const [categories, setCategories] = useState<CategoriesData | null>(null);
  const [income, setIncome] = useState<IncomeData | null>(null);
  const [wealth, setWealth] = useState<WealthData | null>(null);

  // Nuovi dati
  const [capitalTrend, setCapitalTrend] = useState<CapitalTrendData | null>(null);
  const [topMerchants, setTopMerchants] = useState<TopMerchantsData | null>(null);
  const [budgetStatus, setBudgetStatus] = useState<BudgetStatusData | null>(null);
  const [savingsRate, setSavingsRate] = useState<SavingsRateData | null>(null);
  const [monthComparison, setMonthComparison] = useState<MonthComparisonData | null>(null);
  const [planType, setPlanType] = useState<string>("free");
  const isPro = planType === "pro";

  // Max months slider
  const maxMonths = isPro ? 24 : 6;

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

  const loadData = useCallback(async (m: number, id: string | null) => {
    setLoading(true);
    setError(null);
    try {
      const monthStr = String(m);
      // Richiedi sempre il limite Pro (10) — il backend lo capperà per utenti Free
      const [ov, cat, inc, wea, cap, mer] = await Promise.all([
        fetchApi<OverviewData>("/api/analytics/overview", id, { months: monthStr }),
        fetchApi<CategoriesData>("/api/analytics/categories-expense", id, { months: monthStr }),
        fetchApi<IncomeData>("/api/analytics/income", id, { months: monthStr }),
        fetchApi<WealthData>("/api/analytics/wealth", id, {}),
        fetchApi<CapitalTrendData>("/api/analytics/capital-trend", id, { months: monthStr }),
        fetchApi<TopMerchantsData>("/api/analytics/top-merchants", id, { months: monthStr, limit: "10" }),
      ]);
      setOverview(ov);
      setCategories(cat);
      setIncome(inc);
      setWealth(wea);
      setCapitalTrend(cap);
      setTopMerchants(mer);

      // Determina plan_type dalla prima risposta che lo contiene
      const pt = ov.plan_type || cat.plan_type || inc.plan_type || wea.plan_type || "free";
      setPlanType(pt);

      // Carica dati Pro-only se l'utente è Pro
      if (pt === "pro") {
        const [bud, sr, mc] = await Promise.all([
          fetchApi<BudgetStatusData>("/api/analytics/budget-status", id, {}),
          fetchApi<SavingsRateData>("/api/analytics/savings-rate", id, { months: monthStr }),
          fetchApi<MonthComparisonData>("/api/analytics/month-comparison", id, {}),
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
  }, []);

  useEffect(() => {
    if (!mounted) return;
    if (isTelegram) {
      if (!initData) {
        setError("auth_401");
        setLoading(false);
      } else {
        loadData(months, initData);
      }
    } else {
      loadData(months, null);
    }
  }, [isTelegram, initData, months, loadData, mounted]);

  const handleMonthsChange = (v: number) => {
    setMonths(v);
  };

  if (!mounted) return null;

  const isNgrok = typeof window !== "undefined" && window.location.hostname.includes("ngrok-free.app");
  const showHeader = !isTelegram && !isNgrok;

  // Categorie uniche per il filtro
  const uniqueCategories = [...new Set((categories?.by_category ?? []).map((e) => e.name))].sort();

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
          <Typography variant="h5" fontWeight={700} color="primary" mb={1}>
            📊 Analytics
          </Typography>
          <Typography variant="body2" color="text.secondary" mb={3}>
            Analisi delle tue finanze con Moneo
          </Typography>
        </>
      )}

      <PeriodSlider value={months} onChange={handleMonthsChange} maxMonths={maxMonths} />

      <Tabs
        value={tab}
        onChange={(_, v) => setTab(v)}
        sx={{ mb: 2, minHeight: 40 }}
        variant="scrollable"
        scrollButtons="auto"
        allowScrollButtonsMobile
      >
        <Tab label="📈 Panoramica" sx={{ fontSize: "0.75rem", minHeight: 40 }} />
        <Tab label="💳 Spese" sx={{ fontSize: "0.75rem", minHeight: 40 }} />
        <Tab label="💰 Entrate" sx={{ fontSize: "0.75rem", minHeight: 40 }} />
        <Tab label="📋 Lista" sx={{ fontSize: "0.75rem", minHeight: 40 }} />
        <Tab
          label={
            <Box sx={{ display: "flex", alignItems: "center", gap: 0.5 }}>
              🎯 Budget
              {!isPro && (
                <Chip
                  label="PRO"
                  size="small"
                  sx={{
                    background: "linear-gradient(135deg, #C5A059, #D4B47A)",
                    color: "#ffffff",
                    fontWeight: 800,
                    fontSize: "0.6rem",
                    height: 18,
                  }}
                />
              )}
            </Box>
          }
          sx={{ fontSize: "0.75rem", minHeight: 40 }}
        />
      </Tabs>

      {loading && (
        <Box display="flex" justifyContent="center" py={6}>
          <CircularProgress color="primary" />
        </Box>
      )}

      {error && !loading && (
        <Alert severity="error" sx={{ mb: 2 }}>
          {error === "auth_401"
            ? (isTelegram
              ? "Sessione Telegram scaduta — riapri la mini-app dal bot."
              : "Apri questa pagina dalla mini-app Telegram.")
            : error}
        </Alert>
      )}

      {!loading && !error && overview && categories && income && wealth && capitalTrend && topMerchants && (
        <>
          {/* Tab 0: Panoramica */}
          {tab === 0 && (
            <>
              <CapitalTrendChart data={capitalTrend} isPro={isPro} />
              <SavingsChart data={overview.savings} />
              {isPro && savingsRate && (
                <SavingsRateChart data={savingsRate} />
              )}
              {!isPro && (
                <PremiumGate isPro={false} featureName="Tasso di Risparmio">
                  <SavingsRateChart data={{ savings_rate: [], plan_type: "free", error: "Pro required" }} />
                </PremiumGate>
              )}
              <MonthlyByAccountChart rows={overview.totals_by_account} />
            </>
          )}

          {/* Tab 1: Spese */}
          {tab === 1 && (
            <>
              <CategoryTrendChart
                rows={categories.by_category}
                categories={uniqueCategories}
                isPro={isPro}
              />
              <CategoryPieChart rows={categories.by_category} />
              <CategoryHistoryChart rows={categories.by_category} />
              {topMerchants && <TopMerchantsChart data={topMerchants} />}
              <CategoryAvgChart avgs={categories.averages} />
              {isPro && monthComparison && (
                <MonthComparisonChart data={monthComparison} />
              )}
              {!isPro && (
                <PremiumGate isPro={false} featureName="Confronto Mensile">
                  <MonthComparisonChart data={{ comparisons: [], plan_type: "free", error: "Pro required" }} />
                </PremiumGate>
              )}
            </>
          )}

          {/* Tab 2: Entrate */}
          {tab === 2 && (
            <>
              <IncomeChart data={income.monthly} />
              <WealthPieChart accounts={wealth.accounts} />
            </>
          )}

          {/* Tab 3: Lista Transazioni */}
          {tab === 3 && (
            <TransactionsTable
              data={{ transactions: [], total: 0, total_amount: 0, offset: 0, limit: 50, plan_type: planType }}
              isPro={isPro}
              initData={initData}
            />
          )}

          {/* Tab 4: Budget (Pro) */}
          {tab === 4 && (
            isPro && budgetStatus ? (
              <BudgetGaugeList data={budgetStatus} />
            ) : (
              <PremiumGate isPro={false} featureName="Stato Budget">
                <BudgetGaugeList data={{ budget_status: [], month: "", total_income: 0, total_spent: 0, plan_type: "free", error: "Pro required" }} />
              </PremiumGate>
            )
          )}
        </>
      )}
    </Box>
  );
}
