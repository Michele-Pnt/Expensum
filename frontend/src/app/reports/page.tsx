"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { CircularProgress } from "@mui/material";
import styles from "./reports.module.css";
import { trackReportViewed, trackReportShared } from "@/lib/analytics";

interface ReportSummary {
  id: number;
  report_type: "weekly" | "monthly";
  report_date: string;
  share_token: string;
  created_at: string;
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
  const [reports, setReports] = useState<ReportSummary[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

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
      .then((data) => setReports(data.reports ?? []))
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
    <div className={styles.container}>
      <div className={styles.header}>
        <h1 className={styles.title}>Storico Report</h1>
        <p className={styles.subtitle}>Report settimanali e mensili generati automaticamente</p>
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
            <span
              className={`${styles.reportBadge} ${r.report_type === "weekly" ? styles.reportBadgeWeekly : ""}`}
            >
              {r.report_type === "weekly" ? "Settimanale" : "Mensile"}
            </span>
          </Link>
        ))}
      </div>
    </div>
  );
}
