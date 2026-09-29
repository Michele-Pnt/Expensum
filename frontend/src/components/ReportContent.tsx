"use client";
/* eslint-disable @typescript-eslint/no-explicit-any */

import React from "react";
import Link from "next/link";
import {
  BarChart, Bar, LineChart, Line,
  XAxis, YAxis, Tooltip, ResponsiveContainer, Legend, CartesianGrid,
} from "recharts";
import { Lock } from "lucide-react";
import styles from "@/app/reports/reports.module.css";
import { canCreateSavingsGoalFromReport } from "@/lib/contextual-navigation";
import { CHART_ACCENT, CHART_NEUTRAL, TOOLTIP_STYLE, TICK_STYLE } from "@/theme/chartPalette";
import {
  buildMonthlyBarData,
  buildWeeklyBarData,
  formatBudgetSpendReadout,
  type BudgetSpendChartRow,
} from "./reportChartData";

export {
  buildMonthlyBarData,
  buildWeeklyBarData,
  formatBudgetSpendReadout,
} from "./reportChartData";
export type { BudgetSpendChartRow } from "./reportChartData";

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

// La spesa per categoria era una torta con la palette categoriale CVD-safe di
// analytics/page.tsx. Ora e' un grafico a barre orizzontali (CategoryBars piu'
// sotto): con le categorie scritte sull'asse il colore non porta piu' identita',
// quindi basta una serie sola nell'accento di brand e la palette categoriale
// qui non serve. Resta in analytics/page.tsx, dove il colore distingue davvero
// fra piu' serie sullo stesso grafico.

/**
 * Spesa per categoria a barre orizzontali, al posto della torta.
 *
 * Una torta con una fetta dominante e tre schegge non si legge, e le etichette
 * finivano in una legenda a 10px troncata a 13 caratteri. Qui le categorie
 * stanno sull'asse, ordinate per importo decrescente, quindi l'identita' e'
 * scritta e non affidata al colore: una serie sola nell'accento di brand.
 */
function CategoryBars({ data }: { data: { name: string; value: number }[] }) {
  const rows = [...data].sort((a, b) => (b.value ?? 0) - (a.value ?? 0));
  // Ogni barra ha bisogno di una fascia fissa, altrimenti con due categorie
  // diventano due bandoni e con otto si schiacciano.
  const height = Math.max(160, rows.length * 34 + 24);

  return (
    <ResponsiveContainer width="100%" height={height}>
      <BarChart
        data={rows}
        layout="vertical"
        margin={{ top: 4, right: 56, bottom: 4, left: 4 }}
        accessibilityLayer={false}
      >
        <XAxis type="number" hide />
        <YAxis
          type="category"
          dataKey="name"
          tick={TICK_STYLE}
          axisLine={false}
          tickLine={false}
          width={92}
        />
        <Tooltip
          cursor={false}
          contentStyle={TOOLTIP_STYLE}
          formatter={(v: any) => `€${(v ?? 0).toFixed(2)}`}
        />
        <Bar
          activeBar={false}
          dataKey="value"
          name="Speso"
          fill={CHART_ACCENT}
          radius={[0, 4, 4, 0]}
          barSize={14}
          label={{
            position: "right",
            fill: CHART_NEUTRAL,
            fontSize: 11,
            formatter: (v: any) => `€${Math.round(v ?? 0)}`,
          }}
        />
      </BarChart>
    </ResponsiveContainer>
  );
}

const PLACEHOLDER_STYLE: React.CSSProperties = {
  display: "flex",
  alignItems: "center",
  justifyContent: "center",
  height: 180,
  color: "#B0B5B9",
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
  if (Number.isNaN(d.getTime())) return "";
  const day = String(d.getDate()).padStart(2, "0");
  const month = String(d.getMonth() + 1).padStart(2, "0");
  return `${day}-${month}-${d.getFullYear()}`;
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

// ---------------------------------------------------------------------------
// Schema strutturato (report_schema.py) — sostituisce il vecchio Markdown
// "per Telegram" in text_content. Un report nuovo ha sempre schema_version=1;
// i report salvati prima di questa modifica restano Markdown grezzo e vengono
// mostrati dal renderer legacy più sotto (non esiste retention su
// saved_reports: vecchi link condivisi possono essere aperti a tempo
// indeterminato, quindi il fallback resta permanente, non solo transitorio).
// ---------------------------------------------------------------------------

type Tone = "neutral" | "positive" | "negative" | "warning" | null | undefined;

interface KpiItem {
  label: string;
  value: string;
  tone: Tone;
}

interface TableColumn {
  key: string;
  label: string;
  align: "left" | "right";
}

interface TableRow {
  cells: Record<string, string>;
  tone: Tone;
}

interface TableSectionData {
  type: "table";
  heading: string;
  columns: TableColumn[];
  rows: TableRow[];
  empty_message: string | null;
}

interface NarrativeSectionData {
  type: "narrative";
  heading: string;
  paragraphs: string[];
}

interface ListSectionData {
  type: "list";
  heading: string;
  items: string[];
  empty_message: string | null;
}

type SectionData = TableSectionData | NarrativeSectionData | ListSectionData;

interface ReportContentV1 {
  schema_version: 1;
  title: string;
  subtitle: string | null;
  kpis: KpiItem[];
  sections: SectionData[];
  locked_from_section: number | null;
  footer_note: string | null;
  referral_url: string | null;
}

function parseReportContent(text: string): ReportContentV1 | null {
  try {
    const parsed = JSON.parse(text);
    if (
      parsed &&
      typeof parsed === "object" &&
      parsed.schema_version === 1 &&
      typeof parsed.title === "string" &&
      Array.isArray(parsed.kpis) &&
      Array.isArray(parsed.sections)
    ) {
      return parsed as ReportContentV1;
    }
  } catch {
    // Non è JSON: report legacy salvato prima dello schema strutturato.
  }
  return null;
}

const toneClass = (tone: Tone): string | undefined => {
  if (tone === "positive") return styles.rowPositive;
  if (tone === "negative") return styles.rowNegative;
  if (tone === "warning") return styles.rowWarning;
  return undefined;
};

const kpiToneClass = (tone: Tone): string | undefined => {
  if (tone === "positive") return styles.kpiPositive;
  if (tone === "negative") return styles.kpiNegative;
  if (tone === "warning") return styles.kpiWarning;
  return undefined;
};

function KpiGrid({ kpis }: { kpis: KpiItem[] }) {
  if (kpis.length === 0) return null;
  return (
    <div className={styles.kpiGrid}>
      {kpis.map((k, i) => (
        <div key={i} className={`${styles.kpiCard} ${kpiToneClass(k.tone) ?? ""}`}>
          <p className={styles.kpiLabel}>{k.label}</p>
          <p className={styles.kpiValue}>{k.value}</p>
        </div>
      ))}
    </div>
  );
}

function TableSectionView({ section }: { section: TableSectionData }) {
  return (
    <div className={styles.sectionBlock}>
      <p className={styles.sectionHeading}>{section.heading}</p>
      {section.rows.length === 0 ? (
        <p className={styles.emptyMessage}>{section.empty_message}</p>
      ) : (
        <div className={styles.tableWrap}>
          <table className={styles.dataTable}>
            <thead>
              <tr>
                {section.columns.map((col) => (
                  <th key={col.key} className={col.align === "right" ? styles.alignRight : undefined}>
                    {col.label}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {section.rows.map((row, i) => (
                <tr key={i} className={toneClass(row.tone)}>
                  {section.columns.map((col) => (
                    <td
                      key={col.key}
                      className={col.align === "right" ? styles.alignRight : undefined}
                      data-label={col.label}
                    >
                      {row.cells[col.key] ?? ""}
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

function NarrativeSectionView({ section }: { section: NarrativeSectionData }) {
  return (
    <div className={styles.sectionBlock}>
      <p className={styles.sectionHeading}>{section.heading}</p>
      {section.paragraphs.map((p, i) => (
        <p key={i} className={styles.narrativeParagraph}>{p}</p>
      ))}
    </div>
  );
}

function ListSectionView({ section }: { section: ListSectionData }) {
  return (
    <div className={styles.sectionBlock}>
      <p className={styles.sectionHeading}>{section.heading}</p>
      {section.items.length === 0 ? (
        <p className={styles.emptyMessage}>{section.empty_message}</p>
      ) : (
        <ul className={styles.bulletList}>
          {section.items.map((item, i) => (
            <li key={i} className={styles.bulletItem}>{item}</li>
          ))}
        </ul>
      )}
    </div>
  );
}

function SectionView({ section }: { section: SectionData }) {
  if (section.type === "table") return <TableSectionView section={section} />;
  if (section.type === "list") return <ListSectionView section={section} />;
  return <NarrativeSectionView section={section} />;
}

// Renderer del nuovo schema strutturato: KPI sempre visibili, sezioni prima di
// `locked_from_section` sempre visibili (il "peek" per il piano Free), il
// resto sfocato con la stessa overlay CTA del report legacy quando `locked`.
function StructuredReportBody({ content, locked }: { content: ReportContentV1; locked: boolean }) {
  const total = content.sections.length;
  const rawLockFrom = content.locked_from_section;
  // Un valore fuori range (indice negativo o oltre la fine) non deve mai far
  // "fallire aperto" il paywall: viene sempre bloccato dallo 0 in tal caso,
  // mai mostrato tutto in chiaro (a differenza di un semplice check `< length`).
  const hasLockPoint = locked && rawLockFrom !== null && rawLockFrom !== undefined;
  const lockFrom = hasLockPoint ? Math.max(0, Math.min(rawLockFrom as number, total)) : total;
  const showLock = hasLockPoint && lockFrom < total;
  const visibleSections = content.sections.slice(0, lockFrom);
  const hiddenSections = content.sections.slice(lockFrom);

  return (
    <div className={styles.reportDoc}>
      <p className={styles.reportDocHeader}>{content.title}</p>
      <KpiGrid kpis={content.kpis} />
      {visibleSections.map((s, i) => (
        <SectionView key={i} section={s} />
      ))}
      {showLock ? (
        <div className={styles.peekWrap}>
          <div className={styles.lockedSections} aria-hidden="true">
            {hiddenSections.map((s, i) => (
              <SectionView key={i} section={s} />
            ))}
          </div>
          <div className={styles.lockedOverlay}>
            <p className={styles.lockedOverlayTitle}>
              <Lock size={16} strokeWidth={2} aria-hidden="true" style={{ verticalAlign: "-2px", marginRight: "0.3rem" }} />
              Continua a leggere con Premium
            </p>
            <p className={styles.lockedOverlayText}>
              Dal secondo mese i report Free si sfocano, per sbloccarli passa a Premium!
            </p>
            <Link href="/abbonamenti#premium" className={styles.lockedCta}>
              Passa a Premium
            </Link>
          </div>
        </div>
      ) : null}
      {content.footer_note && <p className={styles.emptyMessage}>{content.footer_note}</p>}
      {content.referral_url && (
        <p className={styles.referralNote}>
          🎁 <a href={content.referral_url}>Invita un amico e sblocca ricompense</a>
        </p>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Renderer legacy (Markdown "per Telegram") — solo per report salvati prima
// dello schema strutturato. Non toccare: nessun report nuovo lo attraversa più.
// ---------------------------------------------------------------------------

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

/**
 * Tooltip esplicito per evitare che l'ordine o le chiavi interne di Recharts
 * facciano sembrare invertiti budget e spesa dopo il tap su una categoria.
 */
export function BudgetSpendTooltip({
  active,
  payload,
}: {
  active?: boolean;
  payload?: Array<{ payload?: BudgetSpendChartRow }>;
}): React.ReactElement | null {
  const row = payload?.[0]?.payload;
  if (!active || !row) return null;
  const [budget, spent] = formatBudgetSpendReadout(row);

  return (
    <div style={TOOLTIP_STYLE}>
      <p style={{ margin: "0 0 0.35rem", fontWeight: 700 }}>{row.name}</p>
      <p style={{ margin: 0 }}>{budget}</p>
      <p style={{ margin: "0.2rem 0 0" }}>{spent}</p>
    </div>
  );
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
          <BarChart data={barData} margin={{ top: 4, right: 8, left: 0, bottom: 40 }} accessibilityLayer={false}>
            <XAxis dataKey="axisLabel" tick={TICK_STYLE} angle={-35} textAnchor="end" interval={0} />
            <YAxis tick={TICK_STYLE} width={40} />
            <Tooltip cursor={false} content={<BudgetSpendTooltip />} />
            <Legend wrapperStyle={{ fontSize: 11, color: "#B0B5B9" }} />
            <Bar activeBar={false} dataKey="Budget" fill="#5FC4CB" radius={[3, 3, 0, 0]} />
            <Bar activeBar={false} dataKey="Speso" fill="#B0B5B9" radius={[3, 3, 0, 0]} />
          </BarChart>
        </ResponsiveContainer>
      </div>

      <div className={styles.chartCard}>
        <div className={styles.chartTitle}>Distribuzione Spesa</div>
        {pieData.length > 0 ? (
          <CategoryBars data={pieData} />
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
            <CategoryBars data={pieData} />
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
              <BarChart data={barRows} margin={{ top: 4, right: 8, left: 0, bottom: 40 }} accessibilityLayer={false}>
                <XAxis dataKey="axisLabel" tick={TICK_STYLE} angle={-35} textAnchor="end" interval={0} />
                <YAxis tick={TICK_STYLE} width={40} />
                <Tooltip cursor={false} content={<BudgetSpendTooltip />} />
                <Legend wrapperStyle={{ fontSize: 11, color: "#B0B5B9" }} />
                <Bar activeBar={false} dataKey="Budget" fill="#5FC4CB" radius={[3, 3, 0, 0]} />
                {hasSpent && <Bar activeBar={false} dataKey="Speso" fill="#B0B5B9" radius={[3, 3, 0, 0]} />}
              </BarChart>
            </ResponsiveContainer>
          </div>
        )}
      </div>

      {historyData.length > 0 ? (
        <div className={styles.chartCard} style={{ marginTop: 12 }}>
          <div className={styles.chartTitle}>Storico mensile: Entrate / Spese / Risparmio (€)</div>
          <ResponsiveContainer width="100%" height={220}>
            <LineChart data={historyData} margin={{ top: 4, right: 8, left: 0, bottom: 4 }} accessibilityLayer={false}>
              <CartesianGrid strokeDasharray="3 3" stroke="rgba(176,181,185,0.25)" />
              <XAxis dataKey="month" tick={TICK_STYLE} />
              <YAxis tick={TICK_STYLE} width={48} tickFormatter={(v) => `€${v}`} />
              <Tooltip cursor={false} contentStyle={TOOLTIP_STYLE} formatter={(v: any) => `€${(v ?? 0).toFixed(2)}`} />
              <Legend wrapperStyle={{ fontSize: 11, color: "#B0B5B9" }} />
              <Line activeDot={false} type="monotone" dataKey="income" name="Entrate" stroke="#5FC4CB" strokeWidth={2} dot={false} />
              <Line activeDot={false} type="monotone" dataKey="expenses" name="Spese" stroke="#E66767" strokeWidth={2} dot={false} />
              <Line activeDot={false} type="monotone" dataKey="net" name="Risparmio" stroke="#B0B5B9" strokeWidth={2} dot={false} />
            </LineChart>
          </ResponsiveContainer>
        </div>
      ) : (
        <div className={styles.chartCard} style={{ marginTop: 12 }}>
          <div className={styles.chartTitle}>Storico mensile: Entrate / Spese / Risparmio (€)</div>
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

  const structured = parseReportContent(report.text_content);

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
        {structured ? (
          <StructuredReportBody content={structured} locked={isLocked} />
        ) : (
          <LegacyReportBody text={report.text_content} locked={isLocked} />
        )}
      </div>
      {canCreateSavingsGoalFromReport(report) && (
        <div className={styles.savingsGoalCta}>
          <p>Hai chiuso il mese con un risparmio netto positivo.</p>
          <Link href="/goals" className={styles.savingsGoalCtaLink}>Crea un obiettivo</Link>
        </div>
      )}
    </div>
  );
}

// Report salvati prima dello schema strutturato (Markdown "per Telegram").
function LegacyReportBody({ text, locked }: { text: string; locked: boolean }) {
  const { header, body } = splitReportHeader(stripTelegramMarkdown(text));

  if (!locked) {
    return (
      <div className={styles.reportDoc}>
        {header && <p className={styles.reportDocHeader}>{header}</p>}
        {renderReportBody(body)}
      </div>
    );
  }

  const { peek, rest } = splitReportPeek(body);
  return (
    <div className={styles.reportDoc}>
      {header && <p className={styles.reportDocHeader}>{header}</p>}
      <div className={styles.peekWrap}>
        {renderReportBody(peek)}
        {rest && renderReportBody(rest, true)}
        <div className={styles.lockedOverlay}>
          <p className={styles.lockedOverlayTitle}>
            <Lock size={16} strokeWidth={2} aria-hidden="true" style={{ verticalAlign: "-2px", marginRight: "0.3rem" }} />
            Continua a leggere con Premium
          </p>
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
}
