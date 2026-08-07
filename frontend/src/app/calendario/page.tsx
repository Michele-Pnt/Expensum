"use client";

import { useEffect, useState, useCallback, useMemo } from "react";
import { Box, Drawer, CircularProgress, Alert } from "@mui/material";
import { ChevronLeft, ChevronRight, Receipt, RefreshCw } from "lucide-react";
import styles from "./calendario.module.css";

// ---------------------------------------------------------------------------
// Tipi
// ---------------------------------------------------------------------------

interface DayExpense {
  id: number;
  name: string;
  amount: number;
  category: string;
}

interface DaySubscriptionOccurrence {
  subscription_id: number;
  name: string;
  amount: number | null;
}

interface DayData {
  expenses: DayExpense[];
  subscription_occurrences: DaySubscriptionOccurrence[];
}

interface CalendarMonthResponse {
  year: number;
  month: number;
  days: Record<string, DayData>;
}

// ---------------------------------------------------------------------------
// Auth Telegram (stesso pattern di analytics/page.tsx)
// ---------------------------------------------------------------------------

const API_BASE = process.env.NEXT_PUBLIC_API_URL ?? "";

type TelegramWebApp = {
  initData?: string;
  ready: () => void;
  expand: () => void;
};

type TelegramWindow = Window & {
  Telegram?: { WebApp?: TelegramWebApp };
};

async function fetchApi<T>(path: string, initData: string | null, params: Record<string, string> = {}): Promise<T> {
  const qs = new URLSearchParams(params);
  const url = `${API_BASE}${path}?${qs.toString()}`;
  const headers: HeadersInit = initData ? { "X-Telegram-Init-Data": initData } : {};
  const res = await fetch(url, { headers });
  if (!res.ok) {
    if (res.status === 401) throw new Error("auth_401");
    throw new Error(`Errore API ${res.status}`);
  }
  return res.json() as Promise<T>;
}

// ---------------------------------------------------------------------------
// Helper calendario
// ---------------------------------------------------------------------------

const WEEKDAY_LABELS = ["LUN", "MAR", "MER", "GIO", "VEN", "SAB", "DOM"];
const MONTH_LABELS = [
  "gennaio", "febbraio", "marzo", "aprile", "maggio", "giugno",
  "luglio", "agosto", "settembre", "ottobre", "novembre", "dicembre",
];

function toIso(d: Date): string {
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
}

interface GridCell {
  date: Date;
  iso: string;
  inCurrentMonth: boolean;
}

function buildMonthGrid(year: number, month: number): GridCell[] {
  const firstOfMonth = new Date(year, month - 1, 1);
  const mondayOffset = (firstOfMonth.getDay() + 6) % 7; // 0 = lunedì
  const gridStart = new Date(year, month - 1, 1 - mondayOffset);

  const cells: GridCell[] = [];
  for (let i = 0; i < 42; i++) {
    const d = new Date(gridStart);
    d.setDate(gridStart.getDate() + i);
    cells.push({ date: d, iso: toIso(d), inCurrentMonth: d.getMonth() === month - 1 });
  }
  return cells;
}

function formatDayLong(iso: string): string {
  const [y, m, d] = iso.split("-").map(Number);
  return `${d} ${MONTH_LABELS[m - 1]} ${y}`;
}

function formatAmount(amount: number | null): string {
  if (amount === null) return "—";
  return amount.toLocaleString("it-IT", { style: "currency", currency: "EUR" });
}

// ---------------------------------------------------------------------------
// Pagina
// ---------------------------------------------------------------------------

export default function CalendarioPage() {
  const today = useMemo(() => new Date(), []);
  const [year, setYear] = useState(today.getFullYear());
  const [month, setMonth] = useState(today.getMonth() + 1);

  const [initData, setInitData] = useState<string | null>(null);
  const [isTelegram, setIsTelegram] = useState(false);
  const [mounted, setMounted] = useState(false);

  const [data, setData] = useState<CalendarMonthResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const [selectedIso, setSelectedIso] = useState<string | null>(null);

  useEffect(() => {
    const tg = (window as TelegramWindow).Telegram?.WebApp;
    const id = tg?.initData ?? "";
    if (tg && id.length > 0) {
      tg.ready();
      tg.expand();
      setIsTelegram(true);
      setInitData(id);
    }
    setMounted(true);
  }, []);

  const loadMonth = useCallback(async (y: number, m: number, id: string | null) => {
    setLoading(true);
    setError(null);
    try {
      const res = await fetchApi<CalendarMonthResponse>("/api/calendar/month", id, {
        year: String(y),
        month: String(m),
      });
      setData(res);
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : "Errore nel caricamento del calendario");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    if (!mounted) return;
    if (isTelegram && !initData) {
      setError("auth_401");
      setLoading(false);
      return;
    }
    loadMonth(year, month, initData);
  }, [mounted, isTelegram, initData, year, month, loadMonth]);

  const grid = useMemo(() => buildMonthGrid(year, month), [year, month]);
  const todayIso = useMemo(() => toIso(today), [today]);

  const goPrevMonth = () => {
    setSelectedIso(null);
    if (month === 1) { setYear((y) => y - 1); setMonth(12); } else { setMonth((m) => m - 1); }
  };
  const goNextMonth = () => {
    setSelectedIso(null);
    if (month === 12) { setYear((y) => y + 1); setMonth(1); } else { setMonth((m) => m + 1); }
  };

  const selectedDay: DayData | null = selectedIso ? data?.days[selectedIso] ?? { expenses: [], subscription_occurrences: [] } : null;

  return (
    <Box className={styles.page}>
      <div className={styles.headerRow}>
        <span className={styles.monthLabel}>{MONTH_LABELS[month - 1]} {year}</span>
        <div className={styles.navButtons}>
          <button className={styles.navButton} onClick={goPrevMonth} aria-label="Mese precedente">
            <ChevronLeft size={18} />
          </button>
          <button className={styles.navButton} onClick={goNextMonth} aria-label="Mese successivo">
            <ChevronRight size={18} />
          </button>
        </div>
      </div>

      {error === "auth_401" && (
        <Alert severity="warning" sx={{ mb: 2 }}>
          Sessione non valida. Riapri la pagina da Telegram.
        </Alert>
      )}
      {error && error !== "auth_401" && (
        <Alert severity="error" sx={{ mb: 2 }}>{error}</Alert>
      )}

      {loading && !data ? (
        <Box sx={{ display: "flex", justifyContent: "center", py: 6 }}>
          <CircularProgress size={28} />
        </Box>
      ) : (
        <>
          <div className={styles.weekdayRow}>
            {WEEKDAY_LABELS.map((w) => (
              <span key={w} className={styles.weekday}>{w}</span>
            ))}
          </div>

          <div className={styles.grid}>
            {grid.map((cell) => {
              const dayData = data?.days[cell.iso];
              const hasExpense = Boolean(dayData?.expenses.length);
              const hasSubscription = Boolean(dayData?.subscription_occurrences.length);
              const isSelected = selectedIso === cell.iso;
              const isToday = cell.iso === todayIso;

              return (
                <button
                  key={cell.iso}
                  className={styles.cell}
                  onClick={() => setSelectedIso(cell.iso)}
                  disabled={!hasExpense && !hasSubscription}
                >
                  <span
                    className={[
                      styles.dayNumber,
                      !cell.inCurrentMonth ? styles.dayNumberOutside : "",
                      isToday && !isSelected ? styles.dayNumberToday : "",
                      isSelected ? styles.dayNumberSelected : "",
                    ].join(" ").trim()}
                  >
                    {cell.date.getDate()}
                  </span>
                  <span className={styles.dots}>
                    {hasExpense && <span className={styles.dotExpense} />}
                    {hasSubscription && <span className={styles.dotSubscription} />}
                  </span>
                </button>
              );
            })}
          </div>
        </>
      )}

      <Drawer
        anchor="bottom"
        open={Boolean(selectedIso)}
        onClose={() => setSelectedIso(null)}
        PaperProps={{ sx: { borderTopLeftRadius: 16, borderTopRightRadius: 16, maxHeight: "70vh" } }}
      >
        <div className={styles.sheetHandle} />
        {selectedIso && (
          <>
            <div className={styles.sheetHeader}>
              <div className={styles.sheetTitle}>{formatDayLong(selectedIso)}</div>
              <div className={styles.sheetSubtitle}>
                {(selectedDay?.expenses.length ?? 0) + (selectedDay?.subscription_occurrences.length ?? 0)} voci
              </div>
            </div>

            {selectedDay && selectedDay.expenses.length === 0 && selectedDay.subscription_occurrences.length === 0 && (
              <div className={styles.emptyState}>Nessuna spesa o abbonamento in questo giorno.</div>
            )}

            {selectedDay?.expenses.map((exp) => (
              <div className={styles.itemRow} key={`exp-${exp.id}`}>
                <span className={`${styles.itemIcon} ${styles.itemIconExpense}`}>
                  <Receipt size={18} />
                </span>
                <span className={styles.itemBody}>
                  <div className={styles.itemName}>{exp.name || "Spesa"}</div>
                  <div className={styles.itemMeta}>{exp.category}</div>
                </span>
                <span className={styles.itemAmount}>{formatAmount(exp.amount)}</span>
              </div>
            ))}

            {selectedDay?.subscription_occurrences.map((occ) => (
              <div className={styles.itemRow} key={`sub-${occ.subscription_id}-${selectedIso}`}>
                <span className={`${styles.itemIcon} ${styles.itemIconSubscription}`}>
                  <RefreshCw size={18} />
                </span>
                <span className={styles.itemBody}>
                  <div className={styles.itemName}>{occ.name || "Abbonamento"}</div>
                  <div className={styles.itemMeta}>Addebito previsto</div>
                </span>
                <span className={styles.itemAmount}>{formatAmount(occ.amount)}</span>
              </div>
            ))}
          </>
        )}
      </Drawer>
    </Box>
  );
}
