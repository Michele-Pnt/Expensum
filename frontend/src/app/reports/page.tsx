"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { CircularProgress } from "@mui/material";
import { Lock } from "lucide-react";
import styles from "./reports.module.css";
import { trackReportViewed, trackReportShared } from "@/lib/analytics";
import { getCsrfToken } from "@/lib/csrf";

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

export default function ReportsPage() {
  const router = useRouter();
  const [reports, setReports] = useState<ReportSummary[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [generating, setGenerating] = useState<"weekly" | "monthly" | null>(null);
  const [generateError, setGenerateError] = useState<string | null>(null);
  const [isPro, setIsPro] = useState(false);

  async function handleGenerate(type: "weekly" | "monthly") {
    setGenerating(type);
    setGenerateError(null);
    try {
      const telegramWindow = window as TelegramWindow;
      const initData = telegramWindow.Telegram?.WebApp?.initData ?? "";
      const csrfToken = await getCsrfToken();
      const headers: HeadersInit = {
        "Content-Type": "application/json",
        "X-CSRFToken": csrfToken,
      };
      if (initData) headers["X-Telegram-Init-Data"] = initData;

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
        router.push(`/reports/${data.share_token}`);
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
    const telegramWindow = window as TelegramWindow;
    const initData = telegramWindow.Telegram?.WebApp?.initData ?? "";
    const headers: HeadersInit = initData ? { "X-Telegram-Init-Data": initData } : {};

    fetch(`${API_BASE}/api/reports`, { headers })
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
  }, []);

  if (loading) {
    return (
      <div className={styles.container}>
        <div className={styles.loading}>
          <CircularProgress size={32} color="primary" />
        </div>
      </div>
    );
  }

  return (
    <div className={styles.container} data-tour="reports-list">
      <div className={styles.header}>
        <h1 className={styles.title}>Storico Report</h1>
        <p className={styles.subtitle}>Report settimanali e mensili generati automaticamente</p>
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

      <div className={styles.list}>
        {reports.map((r) => (
          <Link
            key={r.share_token}
            href={`/reports/${r.share_token}`}
            className={styles.reportCard}
            onClick={() => trackReportShared(r.report_type)}
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
                {r.report_type === "weekly" ? "Settimanale" : "Mensile"}
              </span>
            </div>
          </Link>
        ))}
      </div>
    </div>
  );
}
