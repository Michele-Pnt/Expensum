"use client";
/* eslint-disable @typescript-eslint/no-explicit-any */

import React from "react";
import Link from "next/link";
import {
  BarChart, Bar, LineChart, Line, PieChart, Pie, Cell,
  XAxis, YAxis, Tooltip, ResponsiveContainer, Legend, CartesianGrid,
} from "recharts";
import styles from "@/app/reports/reports.module.css";

// ---------------------------------------------------------------------------
// Tipi
// ---------------------------------------------------------------------------

export interface ReportDetail {
  id: number;
  report_type: "weekly" | "monthly" | "monthly_full";
  report_date: string;
  share_token: string;
  text_content: string;
  report_data: Record<string, any> | null;
  created_at: string;
  plan_type?: string;
  locked?: boolean;
}

// ---------------------------------------------------------------------------
// Costanti
// ---------------------------------------------------------------------------

const PALETTE = ["#1A3673", "#C5A059", "#4B6CB7", "#7C9BD6", "#A8853C", "#2B4FA8", "#D4B47A", "#6B7280", "#9DB4D8"];

const TOOLTIP_STYLE = {
  background: "#FFFFFF",
  border: "1px solid #E5E2DC",
  borderRadius: 8,
  color: "#1A1A1A",
  fontSize: 12,
};

const TICK_STYLE = { fontSize: 10, fill: "#6B7280" };

const PLACEHOLDER_STYLE: React.CSSProperties = {
  display: "flex",
  alignItems: "center",
  justifyContent: "center",
  height: 180,
  color: "#6B7280",
  fontSize: 13,
  textAlign: "center",
  padding: "0 1rem",
};

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

export function formatDate(iso: string): string {
  if (!iso) return "";
  const d = new Date(iso);
  return d.toLocaleDateString("it-IT", { day: "2-digit", month: "long", year: "numeric" });
}

export function buildReportSubtitle(report: ReportDetail): string {
  if (report.report_type === "weekly") {
    return formatDate(report.report_date);
  }
  // report_date rappresenta la data di pubblicazione (1° del mese successivo a
  // quello analizzato), non il mese analizzato: quello va letto da report_data
  // quando disponibile, altrimenti si ricade su report_date per compatibilità
  // con i vecchi report salvati prima di questa distinzione.
  const rd = report.report_data;
  let analyzedMonth: Date;
  if (rd && typeof rd.target_month === "number" && typeof rd.target_year === "number") {
    analyzedMonth = new Date(rd.target_year, rd.target_month - 1, 1);
  } else if (rd && typeof rd.target_month === "string") {
    analyzedMonth = new Date(rd.target_month);
  } else {
    analyzedMonth = new Date(report.report_date);
  }
  const monthLabel = analyzedMonth.toLocaleDateString("it-IT", { month: "long" });
  const monthTitle = monthLabel ? monthLabel.charAt(0).toUpperCase() + monthLabel.slice(1) : "";
  return `Analisi del mese chiuso: ${monthTitle}`;
}

export function stripTelegramMarkdown(text: string): string {
  return text
    .replace(/\*([^*]+)\*/g, "$1")
    .replace(/_([^_]+)_/g, "$1")
    .replace(/```[\s\S]*?```/g, (m) => m.replace(/```/g, "").trim())
    .replace(/`([^`]+)`/g, "$1");
}

// Piano Free, dal secondo mese: mostra solo il primo paragrafo (intro, senza dati
// veri) e sfoca tutto il resto (dove vivono le cifre). Split sul contenuto reale,
// non su un'altezza in px stimata — cosi' i numeri non trapelano mai.
function splitReportPeek(text: string): { peek: string; rest: string } {
  const paragraphs = text.split(/\n{2,}/);
  return {
    peek: paragraphs[0] ?? "",
    rest: paragraphs.slice(1).join("\n\n"),
  };
}

// Separa la prima riga (titolo, es. "📊 Riepilogo di Luglio 2026") dal corpo, cosi'
// possiamo trattarla come intestazione di un documento invece che come testo normale.
function splitReportHeader(text: string): { header: string; body: string } {
  const idx = text.indexOf("\n");
  if (idx === -1) return { header: text.trim(), body: "" };
  return { header: text.slice(0, idx).trim(), body: text.slice(idx + 1).trim() };
}

// Le etichette delle cifre chiave (entrate/uscite/risparmio/categoria) vanno in
// grassetto, come su un vero estratto conto — il valore dopo i due punti resta
// testo normale.
const BOLD_LINE_PREFIXES = [
  "entrate:",
  "uscite:",
  "risparmio netto:",
  "categoria con la spesa maggiore:",
];

function renderReportLines(text: string): React.ReactNode {
  const lines = text.split("\n");
  return lines.map((line, i) => {
    const lower = line.trim().toLowerCase();
    const matchedPrefix = BOLD_LINE_PREFIXES.find((prefix) => lower.startsWith(prefix));
    const colonIdx = line.indexOf(":");
    const content = matchedPrefix && colonIdx !== -1
      ? <><strong>{line.slice(0, colonIdx + 1)}</strong>{line.slice(colonIdx + 1)}</>
      : line;
    return (
      <React.Fragment key={i}>
        {content}
        {i < lines.length - 1 ? "\n" : null}
      </React.Fragment>
    );
  });
}

// Un blocco (paragrafo) è una tabella (es. "Categoria   Scorsa   /sett") se almeno
// due righe hanno colonne allineate a spazi — va mostrato in monospace, altrimenti
// l'allineamento si rompe con il font serif del resto del report.
function isTabularBlock(block: string): boolean {
  const alignedLines = block.split("\n").filter((l) => /\S {2,}\S/.test(l)).length;
  return alignedLines >= 2;
}

// Divide il corpo in blocchi (paragrafi) e sceglie lo stile giusto per ciascuno:
// prose in serif (con le cifre chiave in grassetto), tabelle in monospace allineato.
// hidden=true sfoca il blocco (report bloccato, dal secondo mese su piano Free).
function renderReportBody(text: string, hidden = false): React.ReactNode {
  const blocks = text.split(/\n{2,}/).filter((b) => b.trim() !== "");
  return blocks.map((block, i) => {
    const tabular = isTabularBlock(block);
    const className = tabular
      ? (hidden ? styles.reportTableHidden : styles.reportTable)
      : (hidden ? styles.reportTextHidden : styles.reportText);
    return (
      <pre key={i} className={className} aria-hidden={hidden || undefined}>
        {hidden ? block : renderReportLines(block)}
      </pre>
    );
  });
}

// ---------------------------------------------------------------------------
// Chart builders
// ---------------------------------------------------------------------------

function buildWeeklyBarData(budgetResults: Record<string, any>) {
  return Object.entries(budgetResults)
    .map(([cat, r]) => ({
      name: cat.length > 12 ? cat.slice(0, 11) + "." : cat,
      Budget: Math.round(r.budget_monthly ?? 0),
      Speso: Math.round(r.spent_month ?? 0),
    }))
    .sort((a, b) => b.Budget - a.Budget)
    .slice(0, 8);
}

function buildSpentPieData(budgetResults: Record<string, any>) {
  return Object.entries(budgetResults)
    .map(([cat, r]) => ({ name: cat, value: Math.round(r.spent_month ?? 0) }))
    .filter((e) => e.value > 0)
    .sort((a, b) => b.value - a.value)
    .slice(0, 8);
}

function buildMonthlyPieData(data: Record<string, any>) {
  const source = data.spent_by_cat ?? data.by_category ?? {};
  return Object.entries(source)
    .map(([cat, v]) => ({ name: cat, value: Math.round(Number(v)) }))
    .filter((e) => e.value > 0)
    .sort((a, b) => b.value - a.value)
    .slice(0, 8);
}

function buildMonthlyBarData(data: Record<string, any>): {
  rows: { name: string; Speso: number; Budget: number }[];
  hasSpent: boolean;
} {
  const spent = data.spent_by_cat ?? data.by_category ?? {};
  const budgets = data.budget_by_cat ?? {};
  const hasSpent = Object.values(spent).some((v) => Number(v) > 0);
  const cats = new Set([...Object.keys(hasSpent ? spent : {}), ...Object.keys(budgets)]);
  const rows = Array.from(cats)
    .map((cat) => ({
      name: cat.length > 12 ? cat.slice(0, 11) + "." : cat,
      Speso: Math.round(Number(spent[cat] ?? 0)),
      Budget: Math.round(Number(budgets[cat] ?? 0)),
    }))
    .filter((e) => e.Speso > 0 || e.Budget > 0)
    .sort((a, b) => b.Budget - a.Budget)
    .slice(0, 8);
  return { rows, hasSpent };
}

function buildHistoryData(data: Record<string, any>) {
  const history: Array<{ month: string; income: number; expenses: number; net: number }> =
    data.monthly_history ?? [];
  return history;
}

// ---------------------------------------------------------------------------
// Componenti chart
// ---------------------------------------------------------------------------

export function WeeklyCharts({ data }: { data: Record<string, any> }) {
  const budgetResults = data.budget_results ?? {};
  const barData = buildWeeklyBarData(budgetResults);
  const pieData = buildSpentPieData(budgetResults);

  return (
    <div className={styles.chartsGrid}>
      <div className={styles.chartCard}>
        <div className={styles.chartTitle}>Budget vs Speso (€)</div>
        <ResponsiveContainer width="100%" height={220}>
          <BarChart data={barData} margin={{ top: 4, right: 8, left: 0, bottom: 40 }}>
            <XAxis dataKey="name" tick={TICK_STYLE} angle={-35} textAnchor="end" interval={0} />
            <YAxis tick={TICK_STYLE} width={40} />
            <Tooltip contentStyle={TOOLTIP_STYLE} formatter={(v: any) => `€${(v ?? 0).toFixed(2)}`} />
            <Legend wrapperStyle={{ fontSize: 11, color: "#6B7280" }} />
            <Bar dataKey="Budget" fill="#1A3673" radius={[3, 3, 0, 0]} />
            <Bar dataKey="Speso" fill="#C5A059" radius={[3, 3, 0, 0]} />
          </BarChart>
        </ResponsiveContainer>
      </div>

      <div className={styles.chartCard}>
        <div className={styles.chartTitle}>Distribuzione Spesa</div>
        {pieData.length > 0 ? (
          <ResponsiveContainer width="100%" height={220}>
            <PieChart>
              <Pie data={pieData} dataKey="value" nameKey="name" cx="50%" cy="50%" outerRadius={80} label={false}>
                {pieData.map((_, i) => (
                  <Cell key={i} fill={PALETTE[i % PALETTE.length]} />
                ))}
              </Pie>
              <Tooltip contentStyle={TOOLTIP_STYLE} formatter={(v: any) => `€${(v ?? 0).toFixed(2)}`} />
              <Legend
                wrapperStyle={{ fontSize: 10, color: "#6B7280" }}
                formatter={(val) => (val.length > 14 ? val.slice(0, 13) + "." : val)}
              />
            </PieChart>
          </ResponsiveContainer>
        ) : (
          <div style={PLACEHOLDER_STYLE}>Nessuna spesa registrata questo mese</div>
        )}
      </div>
    </div>
  );
}

export function MonthlyCharts({ data }: { data: Record<string, any> }) {
  const pieData = buildMonthlyPieData(data);
  const { rows: barRows, hasSpent } = buildMonthlyBarData(data);
  const historyData = buildHistoryData(data);

  return (
    <>
      <div className={styles.chartsGrid}>
        <div className={styles.chartCard}>
          <div className={styles.chartTitle}>Spesa mese precedente per categoria</div>
          {pieData.length > 0 ? (
            <ResponsiveContainer width="100%" height={220}>
              <PieChart>
                <Pie data={pieData} dataKey="value" nameKey="name" cx="50%" cy="50%" outerRadius={80} label={false}>
                  {pieData.map((_, i) => (
                    <Cell key={i} fill={PALETTE[i % PALETTE.length]} />
                  ))}
                </Pie>
                <Tooltip contentStyle={TOOLTIP_STYLE} formatter={(v: any) => `€${(v ?? 0).toFixed(2)}`} />
                <Legend
                  wrapperStyle={{ fontSize: 10, color: "#6B7280" }}
                  formatter={(val) => (val.length > 14 ? val.slice(0, 13) + "." : val)}
                />
              </PieChart>
            </ResponsiveContainer>
          ) : (
            <div style={PLACEHOLDER_STYLE}>
              Dati di spesa non disponibili per questo report.<br />Genera un nuovo piano mensile per vederli.
            </div>
          )}
        </div>

        {barRows.length > 0 && (
          <div className={styles.chartCard}>
            <div className={styles.chartTitle}>
              {hasSpent ? "Spesa vs Budget per categoria (€)" : "Budget per categoria (€)"}
            </div>
            <ResponsiveContainer width="100%" height={220}>
              <BarChart data={barRows} margin={{ top: 4, right: 8, left: 0, bottom: 40 }}>
                <XAxis dataKey="name" tick={TICK_STYLE} angle={-35} textAnchor="end" interval={0} />
                <YAxis tick={TICK_STYLE} width={40} />
                <Tooltip contentStyle={TOOLTIP_STYLE} formatter={(v: any) => `€${(v ?? 0).toFixed(2)}`} />
                <Legend wrapperStyle={{ fontSize: 11, color: "#8b949e" }} />
                {hasSpent && <Bar dataKey="Speso" fill="#C5A059" radius={[3, 3, 0, 0]} />}
                <Bar dataKey="Budget" fill="#1A3673" radius={[3, 3, 0, 0]} />
              </BarChart>
            </ResponsiveContainer>
          </div>
        )}
      </div>

      {historyData.length > 0 ? (
        <div className={styles.chartCard} style={{ marginTop: 12 }}>
          <div className={styles.chartTitle}>Storico mensile — Entrate / Spese / Risparmio (€)</div>
          <ResponsiveContainer width="100%" height={220}>
            <LineChart data={historyData} margin={{ top: 4, right: 8, left: 0, bottom: 4 }}>
              <CartesianGrid strokeDasharray="3 3" stroke="#E5E2DC" />
              <XAxis dataKey="month" tick={TICK_STYLE} />
              <YAxis tick={TICK_STYLE} width={48} tickFormatter={(v) => `€${v}`} />
              <Tooltip contentStyle={TOOLTIP_STYLE} formatter={(v: any) => `€${(v ?? 0).toFixed(2)}`} />
              <Legend wrapperStyle={{ fontSize: 11, color: "#6B7280" }} />
              <Line type="monotone" dataKey="income" name="Entrate" stroke="#1A3673" strokeWidth={2} dot={false} />
              <Line type="monotone" dataKey="expenses" name="Spese" stroke="#C5A059" strokeWidth={2} dot={false} />
              <Line type="monotone" dataKey="net" name="Risparmio" stroke="#4B6CB7" strokeWidth={2} dot={false} />
            </LineChart>
          </ResponsiveContainer>
        </div>
      ) : (
        <div className={styles.chartCard} style={{ marginTop: 12 }}>
          <div className={styles.chartTitle}>Storico mensile — Entrate / Spese / Risparmio (€)</div>
          <div style={PLACEHOLDER_STYLE}>
            Storico mensile non disponibile per questo report.<br />Genera un nuovo piano mensile per vederlo.
          </div>
        </div>
      )}
    </>
  );
}

// ---------------------------------------------------------------------------
// Blocco completo report (grafici + testo) — usato sia in modalità
// espansa inline nella lista sia in eventuali altre viste future.
// ---------------------------------------------------------------------------

export function ReportBody({ report }: { report: ReportDetail }) {
  const isWeekly = report.report_type === "weekly";
  const hasChartData = report.report_data !== null;
  const isLocked = report.locked === true;

  const { header, body } = splitReportHeader(stripTelegramMarkdown(report.text_content));

  return (
    <div>
      {hasChartData && (
        <div className={isLocked ? styles.lockedCharts : undefined} aria-hidden={isLocked || undefined}>
          {isWeekly
            ? <WeeklyCharts data={report.report_data!} />
            : <MonthlyCharts data={report.report_data!} />}
        </div>
      )}

      <div className={styles.textCard}>
        <div className={styles.textCardTitle}>Informazioni dettagliate:</div>
        {isLocked ? (() => {
          const { peek, rest } = splitReportPeek(body);
          return (
            <div className={styles.reportDoc}>
              {header && <p className={styles.reportDocHeader}>{header}</p>}
              <div className={styles.peekWrap}>
                {renderReportBody(peek)}
                {rest && renderReportBody(rest, true)}
                <div className={styles.lockedOverlay}>
                  <p className={styles.lockedOverlayTitle}>🔒 Continua a leggere con Premium</p>
                  <p className={styles.lockedOverlayText}>
                    Dal secondo mese i report Free si sfocano, per sbloccarli passa a Premium!
                  </p>
                  <Link href="/abbonamenti#premium" className={styles.lockedCta}>
                    Passa a Premium
                  </Link>
                </div>
              </div>
            </div>
          );
        })() : (
          <div className={styles.reportDoc}>
            {header && <p className={styles.reportDocHeader}>{header}</p>}
            {renderReportBody(body)}
          </div>
        )}
      </div>
    </div>
  );
}
