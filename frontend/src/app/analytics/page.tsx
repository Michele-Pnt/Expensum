"use client";

import { useEffect, useState, useCallback, type ReactNode } from "react";
import {
  Box, Card, CardContent, CardHeader, CircularProgress, Tab, Tabs,
  Typography, Slider, Alert,
} from "@mui/material";
import {
  BarChart, Bar, PieChart, Pie, Cell, XAxis, YAxis, Tooltip,
  ResponsiveContainer, Legend,
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

interface OverviewData { savings: SavingsEntry[]; totals_by_account: AccountMonthEntry[] }
interface CategoriesData { by_category: CategoryEntry[]; averages: CategoryAvg[] }
interface IncomeData { monthly: IncomeEntry[] }
interface WealthData { accounts: AccountBalance[] }

// ---------------------------------------------------------------------------
// Colori
// ---------------------------------------------------------------------------

const PALETTE = ["#008080", "#4caf50", "#03a9f4", "#FF8042", "#8884d8", "#82ca9d", "#ffc658", "#ff7300"];

const INCOME_COLOR = "#4caf50";
const EXPENSE_COLOR = "#ef5350";
const NET_COLOR = "#008080";

// ---------------------------------------------------------------------------
// Fetch helper
// ---------------------------------------------------------------------------

// In sviluppo con rewrites, usiamo percorsi relativi affinché Next.js faccia da proxy.
// Se NEXT_PUBLIC_API_URL è definita (es. in prod), usiamo quella.
const API_BASE = process.env.NEXT_PUBLIC_API_URL ?? "";

function makeHeaders(initData: string | null): HeadersInit {
  return initData ? { "X-Telegram-Init-Data": initData } : {};
}

async function fetchApi<T>(path: string, initData: string | null, months: number): Promise<T> {
  const url = `${API_BASE}${path}?months=${months}`;
  const headers = makeHeaders(initData);
  console.log("fetchApi:", path, "initData:", initData ? initData.substring(0, 20) : "null", "headers:", headers);
  const res = await fetch(url, { headers });
  if (!res.ok) {
    console.error("fetchApi failed:", res.status, await res.text());
    if (res.status === 401) throw new Error("auth_401");
    throw new Error(`Errore API ${res.status}`);
  }
  return res.json() as Promise<T>;
}

async function fetchWealth(initData: string | null): Promise<WealthData> {
  const headers = makeHeaders(initData);
  console.log("fetchWealth: initData:", initData ? initData.substring(0, 20) : "null", "headers:", headers);
  const res = await fetch(`${API_BASE}/api/analytics/wealth`, { headers });
  if (!res.ok) {
    console.error("fetchWealth failed:", res.status, await res.text());
    if (res.status === 401) throw new Error("auth_401");
    throw new Error(`Errore API ${res.status}`);
  }
  return res.json();
}

// ---------------------------------------------------------------------------
// Aggregazioni lato client
// ---------------------------------------------------------------------------

/** Trasforma totals_by_account in format pivot per Stacked BarChart */
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

/** Top 5 categorie per spesa totale, pivot per BarChart raggruppato */
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

const SLIDER_MARKS = [1, 2, 3, 4, 5, 6].map((v) => ({ value: v, label: `${v}` }));

function PeriodSlider({ value, onChange }: { value: number; onChange: (v: number) => void }) {
  return (
    <Box sx={{ px: 2, mb: 3 }}>
      <Typography variant="body2" color="text.secondary" mb={1}>
        Storico: <strong>ultimi {value} {value === 1 ? "mese" : "mesi"}</strong>
      </Typography>
      <Slider
        value={value}
        min={1} max={6} step={1}
        marks={SLIDER_MARKS}
        onChange={(_, v) => onChange(v as number)}
        sx={{ color: "primary.main" }}
      />
    </Box>
  );
}

// ---------------------------------------------------------------------------
// Componenti grafici
// ---------------------------------------------------------------------------

function ChartCard({ title, children }: { title: string; children: ReactNode }) {
  return (
    <Card sx={{ mb: 2, borderRadius: 2 }}>
      <CardHeader title={title} titleTypographyProps={{ variant: "subtitle2", fontWeight: 700 }} sx={{ pb: 1 }} />
      <CardContent sx={{ height: { xs: 200, sm: 260 }, pt: 0 }}>{children}</CardContent>
    </Card>
  );
}

function SavingsChart({ data }: { data: SavingsEntry[] }) {
  return (
    <ChartCard title="Risparmio mensile">
      <ResponsiveContainer width="100%" height="100%">
        <BarChart data={data}>
          <XAxis dataKey="month" tick={{ fontSize: 11 }} />
          <YAxis tick={{ fontSize: 11 }} tickFormatter={(v) => `€${v}`} />
          <Tooltip formatter={(v: any) => `€${(v ?? 0).toFixed(2)}`} />
          <Legend />
          <Bar dataKey="income" name="Entrate" fill={INCOME_COLOR} radius={[4, 4, 0, 0]} />
          <Bar dataKey="expenses" name="Uscite" fill={EXPENSE_COLOR} radius={[4, 4, 0, 0]} />
          <Bar dataKey="net" name="Netto" fill={NET_COLOR} radius={[4, 4, 0, 0]} />
        </BarChart>
      </ResponsiveContainer>
    </ChartCard>
  );
}

function MonthlyByAccountChart({ rows }: { rows: AccountMonthEntry[] }) {
  const data = pivotByAccount(rows);
  const accounts = uniqueAccounts(rows);
  return (
    <ChartCard title="Spesa mensile per conto">
      <ResponsiveContainer width="100%" height="100%">
        <BarChart data={data}>
          <XAxis dataKey="month" tick={{ fontSize: 11 }} />
          <YAxis tick={{ fontSize: 11 }} tickFormatter={(v) => `€${v}`} />
          <Tooltip formatter={(v: any) => `€${(v ?? 0).toFixed(2)}`} />
          <Legend />
          {accounts.map((acc, i) => (
            <Bar key={acc} dataKey={acc} stackId="a" fill={PALETTE[i % PALETTE.length]} />
          ))}
        </BarChart>
      </ResponsiveContainer>
    </ChartCard>
  );
}

function CategoryPieChart({ rows }: { rows: CategoryEntry[] }) {
  // Prende solo l'ultimo mese disponibile
  const months = [...new Set(rows.map((r) => r.month))].sort();
  const lastMonth = months.at(-1);
  const slice = rows.filter((r) => r.month === lastMonth);
  return (
    <ChartCard title={`Spese per categoria (${lastMonth ?? "—"})`}>
      <ResponsiveContainer width="100%" height="100%">
        <PieChart>
          <Pie data={slice} dataKey="amount" nameKey="name" cx="50%" cy="50%"
            innerRadius={55} outerRadius={90} paddingAngle={3}>
            {slice.map((_, i) => <Cell key={i} fill={PALETTE[i % PALETTE.length]} />)}
          </Pie>
          <Tooltip formatter={(v: any) => `€${(v ?? 0).toFixed(2)}`} />
          <Legend iconType="circle" iconSize={10} />
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
        <BarChart data={data}>
          <XAxis dataKey="month" tick={{ fontSize: 11 }} />
          <YAxis tick={{ fontSize: 11 }} tickFormatter={(v) => `€${v}`} />
          <Tooltip formatter={(v: any) => `€${(v ?? 0).toFixed(2)}`} />
          <Legend />
          {cats.map((cat, i) => (
            <Bar key={cat} dataKey={cat} fill={PALETTE[i % PALETTE.length]} radius={[3, 3, 0, 0]} />
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
        <BarChart data={avgs} layout="vertical">
          <XAxis type="number" tick={{ fontSize: 11 }} tickFormatter={(v) => `€${v}`} />
          <YAxis type="category" dataKey="name" tick={{ fontSize: 11 }} width={90} />
          <Tooltip formatter={(v: any) => `€${(v ?? 0).toFixed(2)}`} />
          <Bar dataKey="avg" name="Media" fill="#008080" radius={[0, 4, 4, 0]} />
        </BarChart>
      </ResponsiveContainer>
    </ChartCard>
  );
}

function IncomeChart({ data }: { data: IncomeEntry[] }) {
  return (
    <ChartCard title="Entrate mensili">
      <ResponsiveContainer width="100%" height="100%">
        <BarChart data={data}>
          <XAxis dataKey="month" tick={{ fontSize: 11 }} />
          <YAxis tick={{ fontSize: 11 }} tickFormatter={(v) => `€${v}`} />
          <Tooltip formatter={(v: any) => `€${(v ?? 0).toFixed(2)}`} />
          <Bar dataKey="total" name="Entrate" fill={INCOME_COLOR} radius={[4, 4, 0, 0]} />
        </BarChart>
      </ResponsiveContainer>
    </ChartCard>
  );
}

function WealthPieChart({ accounts }: { accounts: AccountBalance[] }) {
  return (
    <ChartCard title="Capitale per conto">
      <ResponsiveContainer width="100%" height="100%">
        <PieChart>
          <Pie data={accounts} dataKey="balance" nameKey="name" cx="50%" cy="50%"
            innerRadius={55} outerRadius={90} paddingAngle={3}>
            {accounts.map((_, i) => <Cell key={i} fill={PALETTE[i % PALETTE.length]} />)}
          </Pie>
          <Tooltip formatter={(v: any) => `€${(v ?? 0).toFixed(2)}`} />
          <Legend iconType="circle" iconSize={10} />
        </PieChart>
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

  const [overview, setOverview] = useState<OverviewData | null>(null);
  const [categories, setCategories] = useState<CategoriesData | null>(null);
  const [income, setIncome] = useState<IncomeData | null>(null);
  const [wealth, setWealth] = useState<WealthData | null>(null);

  // Rileva contesto Telegram al mount
  useEffect(() => {
    const tg = (window as any).Telegram?.WebApp;
    console.log("Analytics: Telegram WebApp detected:", !!tg);
    if (tg) {
      console.log("Analytics: tg.initData =", JSON.stringify(tg.initData?.substring(0, 50)));
      console.log("Analytics: tg.initData truthy:", !!tg.initData);
      tg.ready();
      tg.expand();
      setIsTelegram(true);
      setInitData(tg.initData ?? null);  // Fix: ?? instead of || to preserve empty string
    } else {
      console.warn("Analytics: Telegram WebApp NOT FOUND");
    }
    setMounted(true);
  }, []);

  const loadData = useCallback(async (m: number, id: string | null) => {
    setLoading(true);
    setError(null);
    try {
      const [ov, cat, inc, wea] = await Promise.all([
        fetchApi<OverviewData>("/api/analytics/overview", id, m),
        fetchApi<CategoriesData>("/api/analytics/categories-expense", id, m),
        fetchApi<IncomeData>("/api/analytics/income", id, m),
        fetchWealth(id),
      ]);
      setOverview(ov);
      setCategories(cat);
      setIncome(inc);
      setWealth(wea);
    } catch (e: any) {
      setError(e.message ?? "Errore nel caricamento dei dati");
    } finally {
      setLoading(false);
    }
  }, []);

  // Primo caricamento dopo che initData è disponibile (o subito se non in Telegram)
  useEffect(() => {
    const tg = (window as any).Telegram?.WebApp;
    if (!tg) {
      // Contesto browser: carica senza auth Telegram
      loadData(months, null);
    }
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    if (isTelegram) {
      if (!initData) {
        setError("auth_401");
        setLoading(false);
      } else {
        loadData(months, initData);
      }
    }
  }, [isTelegram, initData, months, loadData]);

  const handleMonthsChange = (v: number) => {
    setMonths(v);
    loadData(v, initData);
  };

  // Se non siamo ancora "montati" sul browser, non renderizziamo per evitare errori di idratazione
  if (!mounted) return null;

  // Se siamo in Telegram o su un dominio ngrok (probabile Mini App), vogliamo una vista "pulita"
  const isNgrok = typeof window !== "undefined" && window.location.hostname.includes("ngrok-free.app");
  const showHeader = !isTelegram && !isNgrok;

  return (
    <Box sx={{
      p: { xs: 1, sm: 2, md: 3 },
      width: "100%",
      maxWidth: (isTelegram || isNgrok) ? "100%" : 800,
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

      {/* Lo slider lo lasciamo ma più compatto su mobile */}
      <PeriodSlider value={months} onChange={handleMonthsChange} />

      <Tabs
        value={tab}
        onChange={(_, v) => setTab(v)}
        sx={{ mb: 2, minHeight: 40 }}
        variant="fullWidth"
      >
        <Tab label="📈 Panoramica" sx={{ fontSize: "0.75rem", minHeight: 40 }} />
        <Tab label="💳 Spese" sx={{ fontSize: "0.75rem", minHeight: 40 }} />
        <Tab label="💰 Entrate" sx={{ fontSize: "0.75rem", minHeight: 40 }} />
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

      {!loading && !error && overview && categories && income && wealth && (
        <>
          {tab === 0 && (
            <>
              <SavingsChart data={overview.savings} />
              <MonthlyByAccountChart rows={overview.totals_by_account} />
            </>
          )}

          {tab === 1 && (
            <>
              <CategoryPieChart rows={categories.by_category} />
              <CategoryHistoryChart rows={categories.by_category} />
              <CategoryAvgChart avgs={categories.averages} />
            </>
          )}

          {tab === 2 && (
            <>
              <IncomeChart data={income.monthly} />
              <WealthPieChart accounts={wealth.accounts} />
            </>
          )}
        </>
      )}
    </Box>
  );
}
