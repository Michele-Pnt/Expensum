"use client";

import { Suspense, useCallback, useEffect, useState } from "react";
import { useSearchParams } from "next/navigation";
import Link from "next/link";
import { CircularProgress, Select, MenuItem } from "@mui/material";
import type { SelectChangeEvent } from "@mui/material";
import { Lock } from "lucide-react";
import styles from "./reports.module.css";
import { trackReportViewed, trackReportGenerated } from "@/lib/analytics";
import { getCsrfToken } from "@/lib/csrf";
import { ReportBody, type ReportDetail } from "@/components/ReportContent";

interface ReportSummary {
  id: number;
  report_type: "weekly" | "monthly";
  report_date: string;
  share_token: string;
  created_at: string;
  locked?: boolean;
}

type TelegramWindow = Window & {
  Telegram?: {
    WebApp?: {
      initData?: string;
    };
  };
};

const API_BASE = process.env.NEXT_PUBLIC_API_URL ?? "";

function formatDate(iso: string): string {
  if (!iso) return "";
  const d = new Date(iso);
  return d.toLocaleDateString("it-IT", { day: "2-digit", month: "long", year: "numeric" });
}

function authHeaders(): HeadersInit {
  const telegramWindow = window as TelegramWindow;
  const initData = telegramWindow.Telegram?.WebApp?.initData ?? "";
  return initData ? { "X-Telegram-Init-Data": initData } : {};
}

function ReportsPageInner() {
  const searchParams = useSearchParams();
  const highlightToken = searchParams.get("highlight");

  const [reports, setReports] = useState<ReportSummary[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [generating, setGenerating] = useState<"weekly" | "monthly" | null>(null);
  const [generateError, setGenerateError] = useState<string | null>(null);
  const [isPro, setIsPro] = useState(false);
  const [typeFilter, setTypeFilter] = useState<"all" | "weekly" | "monthly">("all");

  const [expandedToken, setExpandedToken] = useState<string | null>(null);
  const [details, setDetails] = useState<Record<string, ReportDetail>>({});
  const [detailLoading, setDetailLoading] = useState<string | null>(null);
  const [detailError, setDetailError] = useState<string | null>(null);

  const loadDetail = useCallback(async (token: string) => {
    setDetailError(null);
    if (details[token]) return;
    setDetailLoading(token);
    try {
      const res = await fetch(`${API_BASE}/api/reports/${token}`, { headers: authHeaders() });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const data: ReportDetail = await res.json();
      setDetails((prev) => ({ ...prev, [token]: data }));
    } catch {
      setDetailError("Impossibile caricare il report. Riprova tra poco.");
    } finally {
      setDetailLoading(null);
    }
  }, [details]);

  function toggleReport(token: string, type: "weekly" | "monthly") {
    if (expandedToken === token) {
      setExpandedToken(null);
      return;
    }
    trackReportViewed(type);
    setExpandedToken(token);
    loadDetail(token);
  }

  async function handleGenerate(type: "weekly" | "monthly") {
    setGenerating(type);
    setGenerateError(null);
    try {
      const csrfToken = await getCsrfToken();
      const headers: HeadersInit = {
        "Content-Type": "application/json",
        "X-CSRFToken": csrfToken,
        ...authHeaders(),
      };

      const res = await fetch(`${API_BASE}/api/reports/generate`, {
        method: "POST",
        headers,
        body: JSON.stringify({ type }),
      });
      if (res.status === 403) {
        setGenerateError("Su piano Free i report sono solo automatici. Passa a Premium per generarli quando vuoi.");
        return;
      }
      if (res.status === 402) {
        setGenerateError("Token mensili insufficienti per generare il report mensile.");
        return;
      }
      if (res.status === 422) {
        setGenerateError("Nessuna transazione trovata per questo periodo: niente da analizzare.");
        return;
      }
      if (!res.ok) throw new Error("generate_failed");
      const data = await res.json();
      if (data.share_token) {
        trackReportGenerated(type);
        // Ricarica lo storico e apre subito la scheda appena generata.
        const listRes = await fetch(`${API_BASE}/api/reports`, { headers: authHeaders() });
        const listData = await listRes.json();
        setReports(listData.reports ?? []);
        setExpandedToken(data.share_token);
        loadDetail(data.share_token);
      } else {
        throw new Error("generate_failed");
      }
    } catch {
      setGenerateError("Generazione non riuscita. Riprova tra poco.");
    } finally {
      setGenerating(null);
    }
  }

  useEffect(() => {
    trackReportViewed("list");
    fetch(`${API_BASE}/api/reports`, { headers: authHeaders() })
      .then((r) => {
        if (r.status === 401) throw new Error("auth_401");
        if (!r.ok) throw new Error("load_failed");
        return r.json();
      })
      .then((data) => {
        setReports(data.reports ?? []);
        setIsPro(data.plan_type === "pro");
      })
      .catch((e) => setError(e.message))
      .finally(() => setLoading(false));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // Se si arriva da un link (Telegram o condiviso) con ?highlight=<token>,
  // apre subito la scheda corrispondente una volta caricato lo storico.
  useEffect(() => {
    if (!highlightToken || loading) return;
    setExpandedToken(highlightToken);
    loadDetail(highlightToken);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [highlightToken, loading]);

  if (loading) {
    return (
      <div className={styles.container}>
        <div className={styles.loading}>
          <CircularProgress size={32} color="primary" />
        </div>
      </div>
    );
  }

  const filteredReports = typeFilter === "all"
    ? reports
    : reports.filter((r) => r.report_type === typeFilter);

  return (
    <div className={styles.container} data-tour="reports-list">
      <div className={styles.header}>
        <div className={styles.headerTop}>
          <div>
            <h1 className={styles.title}>Storico Report</h1>
            <p className={styles.subtitle}>Report settimanali e mensili generati automaticamente</p>
          </div>
          {reports.length > 0 && (
            <Select
              value={typeFilter}
              onChange={(e: SelectChangeEvent) =>
                setTypeFilter(e.target.value as "all" | "weekly" | "monthly")
              }
              size="small"
              sx={{
                minWidth: 170,
                flexShrink: 0,
                fontSize: "0.82rem",
                fontWeight: 600,
                borderRadius: 2,
                background: "var(--color-surface)",
              }}
              MenuProps={{
                PaperProps: {
                  sx: { borderRadius: 2, mt: 0.5 },
                },
              }}
              aria-label="Filtra per tipo di report"
            >
              <MenuItem value="all">Tutti i report</MenuItem>
              <MenuItem value="weekly">Solo settimanali</MenuItem>
              <MenuItem value="monthly">Solo mensili</MenuItem>
            </Select>
          )}
        </div>
        {isPro ? (
          <div className={styles.generateRow}>
            <button
              className={styles.generateBtn}
              disabled={generating !== null}
              onClick={() => handleGenerate("weekly")}
            >
              {generating === "weekly" ? "Generazione..." : "📅 Genera report settimanale"}
            </button>
            <button
              className={styles.generateBtn}
              disabled={generating !== null}
              onClick={() => handleGenerate("monthly")}
            >
              {generating === "monthly" ? "Generazione..." : "📆 Genera report mensile"}
            </button>
          </div>
        ) : (
          <div className={styles.upgradeNote}>
            <div className={styles.upgradeNoteIcon}>
              <Lock size={16} strokeWidth={2.5} />
            </div>
            <div className={styles.upgradeNoteBody}>
              <p className={styles.upgradeNoteTitle}>Report automatici sul piano Free</p>
              <p className={styles.upgradeNoteText}>
                Arrivano ogni lunedì e a inizio mese. Passa a Premium per generarli quando vuoi.
              </p>
            </div>
            <Link href="/abbonamenti#premium" className={styles.upgradeNoteCta}>
              Passa a Premium
            </Link>
          </div>
        )}
        {generateError && <p className={styles.subtitle}>{generateError}</p>}
      </div>

      {error && (
        <div className={styles.empty}>
          <div className={styles.emptyIcon}>⚠️</div>
          <p>
            {error === "auth_401"
              ? "Sessione non valida. Accedi di nuovo per vedere i tuoi report."
              : "Impossibile caricare i report in questo momento."}
          </p>
        </div>
      )}

      {!error && reports.length === 0 && (
        <div className={styles.empty}>
          <div className={styles.emptyIcon}>📊</div>
          <p>Nessun report ancora. Il primo arriverà lunedì mattina!</p>
        </div>
      )}

      {!error && reports.length > 0 && filteredReports.length === 0 && (
        <div className={styles.empty}>
          <div className={styles.emptyIcon}>📭</div>
          <p>Nessun report {typeFilter === "weekly" ? "settimanale" : "mensile"} per ora.</p>
        </div>
      )}

      <div className={styles.list}>
        {filteredReports.map((r) => {
          const isExpanded = expandedToken === r.share_token;
          return (
            <div key={r.share_token}>
              <button
                type="button"
                className={styles.reportCard}
                onClick={() => toggleReport(r.share_token, r.report_type)}
                aria-expanded={isExpanded}
              >
                <div className={styles.reportCardLeft}>
                  <span className={styles.reportIcon}>
                    {r.report_type === "weekly" ? "📅" : "📆"}
                  </span>
                  <div>
                    <div className={styles.reportType}>
                      {r.report_type === "weekly" ? "Report Settimanale" : "Report Mensile"}
                    </div>
                    <div className={styles.reportDate}>{formatDate(r.report_date)}</div>
                  </div>
                </div>
                <div className={styles.reportCardRight}>
                  {r.locked && (
                    <span className={styles.lockBadge} title="Sfocato su piano Free">
                      <Lock size={12} strokeWidth={2.5} />
                    </span>
                  )}
                  <span
                    className={`${styles.reportBadge} ${r.report_type === "weekly" ? styles.reportBadgeWeekly : ""}`}
                  >
                    {isExpanded ? "▲" : "▼"} {r.report_type === "weekly" ? "Settimanale" : "Mensile"}
                  </span>
                </div>
              </button>

              {isExpanded && (
                <div style={{ marginBottom: "1.5rem" }}>
                  {detailLoading === r.share_token && (
                    <div className={styles.loading}>
                      <CircularProgress size={24} color="primary" />
                    </div>
                  )}
                  {detailError && detailLoading !== r.share_token && !details[r.share_token] && (
                    <div className={styles.empty}>
                      <p>{detailError}</p>
                    </div>
                  )}
                  {details[r.share_token] && <ReportBody report={details[r.share_token]} />}
                </div>
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
}

export default function ReportsPage() {
  return (
    <Suspense
      fallback={
        <div className={styles.container}>
          <div className={styles.loading}>
            <CircularProgress size={32} color="primary" />
          </div>
        </div>
      }
    >
      <ReportsPageInner />
    </Suspense>
  );
}
