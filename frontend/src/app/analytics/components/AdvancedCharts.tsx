"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import { Box, Button, Divider, Snackbar, Typography } from "@mui/material";
import { ChevronDown } from "lucide-react";
import {
  Bar, BarChart, Cell, LabelList, Line, LineChart, Pie, PieChart, ResponsiveContainer,
  ReferenceLine, Treemap, XAxis, YAxis,
} from "recharts";
import type { BarRectangleItem, DotItemDotProps } from "recharts";
import AdvancedChartCard from "./AdvancedChartCard";
import LabelFixDialog, { type LabelFixMode, type LabelFixTarget } from "./LabelFixDialog";
import LabelGroupingToggle, { GROUPING_DISCLAIMER } from "./LabelGroupingToggle";
import type { Merchant } from "../types";
import {
  buildCategoryTrendFocus, buildTopCategoryHistory,
  readoutForPeriod, type CategoryRow, type CategoryTrendPoint, type MonthComparisonEntry,
  type IncomeCategorySummary, type IncomeNatureSummary, type IncomeTransaction,
} from "../advancedViewModels";

export function resolveTreemapIndex(node: { name?: string }, items: Array<{ name: string }>): number {
  return Math.max(0, items.findIndex((item) => item.name === node.name));
}

export function resolvePieIndex(_data: unknown, index: number): number {
  return Math.max(0, index);
}

type MerchantOperation ={ id: number; date: string; name: string; normalized_name?: string; amount: number; category: string; account: string };
type Account = { name: string; balance: number };
type LoanSummary = { id: number; status: string; residual_balance: number };
type PeriodMeta = { period_key?: string; period_label?: string; is_partial?: boolean; months_included?: number };
type SavingsPoint = { month: string; income: number; expenses: number; savings: number; net?: number; rate?: number } & PeriodMeta;
type CapitalPoint = { month: string; total: number; [key: string]: string | number | boolean | undefined } & PeriodMeta;
type AccountMonth = { month: string; account: string; amount: number } & PeriodMeta;
type CategoryRowLike = CategoryRow & { month?: string };
type Props = { categories: CategoryRowLike[]; merchants: Merchant[]; accounts: Account[]; comparisons: MonthComparisonEntry[] };
const colors = ["#3987e5", "#d95926", "#199e70", "#c98500", "#d55181"];
const animationProps = { isAnimationActive: true, animationDuration: 350, animationEasing: "ease-out" as const };
const euro = (value: number) => value.toLocaleString("it-IT", { style: "currency", currency: "EUR" });
const formatDisplayDate = (value: string) => {
  const match = value.match(/^(\d{4})-(\d{2})-(\d{2})/);
  return match ? `${match[3]}-${match[2]}-${match[1]}` : value;
};

function ColorLegend({ items }: { items: Array<{ label: string; color: string }> }) {
  return <Box sx={{ display: "flex", flexWrap: "wrap", gap: 1.5 }} aria-label="Legenda grafico">
    {items.map((item) => <Typography key={item.label} component="span" variant="caption" sx={{ color: item.color, fontWeight: 600 }}>
      {item.label}
    </Typography>)}
  </Box>;
}

const monthNames: Record<string, string> = {
  gen: "Gennaio", feb: "Febbraio", mar: "Marzo", apr: "Aprile", mag: "Maggio", giu: "Giugno",
  lug: "Luglio", ago: "Agosto", set: "Settembre", ott: "Ottobre", nov: "Novembre", dic: "Dicembre",
  jan: "Gennaio", may: "Maggio", jun: "Giugno", jul: "Luglio", aug: "Agosto", sep: "Settembre",
  oct: "Ottobre", novem: "Novembre", dec: "Dicembre",
};

function formatCategoryPeriod(point: CategoryTrendPoint): string {
  const label = readoutForPeriod(point);
  const match = label.match(/^([A-Za-zÀ-ÿ]+)\s+(\d{2}|\d{4})$/);
  if (!match) return label;
  const month = monthNames[match[1].toLowerCase().replace(".", "")];
  if (!month) return label;
  const year = match[2].length === 2 ? `20${match[2]}` : match[2];
  return `${month} ${year}`;
}

function formatCompactPeriodRange(start: string, end: string): string {
  const startMatch = start.match(/^([A-Za-zÀ-ÿ]+)\s+(\d{2}|\d{4})$/);
  const endMatch = end.match(/^([A-Za-zÀ-ÿ]+)\s+(\d{2}|\d{4})$/);
  if (!startMatch || !endMatch) return `${start} – ${end}`;
  const startMonth = monthNames[startMatch[1].toLowerCase().replace(".", "")];
  const endMonth = monthNames[endMatch[1].toLowerCase().replace(".", "")];
  if (!startMonth || !endMonth) return `${start} – ${end}`;
  const startYear = startMatch[2].length === 2 ? `20${startMatch[2]}` : startMatch[2];
  const endYear = endMatch[2].length === 2 ? `20${endMatch[2]}` : endMatch[2];
  if (startYear !== endYear) return `${startMonth.slice(0, 3)} ${startYear} – ${endMonth.slice(0, 3)} ${endYear}`;
  return `${startMonth.slice(0, 3)}–${endMonth.slice(0, 3)} ${startYear}`;
}

export function categoryTrendReadout(category: string, point: CategoryTrendPoint, average?: number): string {
  const averageText = average == null ? "" : `\nMedia mensile: ${euro(average)}\n${point.amount >= average ? "Sopra" : "Sotto"} la media`;
  return `${category}: ${euro(point.amount)} · ${formatCategoryPeriod(point)}${averageText}`;
}

export function aggregateSavingsRate(points: SavingsPoint[]) {
  const income = points.reduce((sum, point) => sum + point.income, 0);
  const expenses = points.reduce((sum, point) => sum + point.expenses, 0);
  const savings = income - expenses;
  return { income, expenses, savings, rate: income > 0 ? Math.round((savings / income) * 1000) / 10 : 0 };
}

export function resolveAccountBarReadout(
  datum: Pick<BarRectangleItem, "payload">,
  account: string,
  rows: AccountMonth[],
): AccountMonth | undefined {
  const month = datum.payload?.month;
  return rows.find((row) => row.month === month && row.account === account);
}

function Empty({ label }: { label: string }) {
  return <Box sx={{ minHeight: 220, display: "grid", placeItems: "center" }}><Typography color="text.secondary">{label}</Typography></Box>;
}

function Sparkline({ points, color, width = 80 }: { points: number[]; color: string; width?: number }) {
  const max = Math.max(...points, 1);
  const min = Math.min(...points, 0);
  const span = Math.max(max - min, 1);
  const coordinates = points.map((point, index) => {
    const x = points.length < 2 ? 2 : (index / (points.length - 1)) * (width - 4) + 2;
    const y = 18 - ((point - min) / span) * 14;
    return { x, y };
  });
  const path = coordinates.map(({ x, y }) => `${x},${y}`).join(" ");
  return <svg width={width} height="22" viewBox={`0 0 ${width} 22`} aria-hidden="true">
    <polyline points={path} fill="none" stroke={color} strokeWidth="2" />
    {coordinates.length === 1 && <circle cx={coordinates[0].x} cy={coordinates[0].y} r="3" fill={color} />}
  </svg>;
}

function useReadout<T>(items: T[]) {
  const [index, setIndex] = useState(0);
  const selectIndex = (next: number) => {
    if (Number.isInteger(next) && next >= 0 && next < items.length) setIndex(next);
  };
  return { selected: items[index] ?? items[0], select: (event: unknown) => {
    const chartEvent = event as { activeTooltipIndex?: number | string; activeIndex?: number | string };
    const active = chartEvent.activeTooltipIndex ?? chartEvent.activeIndex;
    const selectedIndex = typeof active === "number" ? active : Number(active);
    if (Number.isInteger(selectedIndex) && selectedIndex >= 0 && selectedIndex < items.length) {
      selectIndex(selectedIndex);
    }
  }, selectIndex, selectWhere: (matcher: (item: T) => boolean) => selectIndex(items.findIndex(matcher)) };
}

function clickableDot(selectIndex: (index: number) => void) {
  return function ClickableDot({ cx, cy, index }: DotItemDotProps) {
    if (cx == null || cy == null) return null;
    return <g onClick={(event) => { event.stopPropagation(); selectIndex(index); }}>
      <circle cx={cx} cy={cy} r={14} fill="transparent" />
      <circle cx={cx} cy={cy} r={4} fill="#5FC4CB" stroke="#F5F7F6" strokeWidth={2} />
    </g>;
  };
}

function OverviewCharts({ savings, capitalTrend, accountRows, savingsRate, accounts: wealthAccounts }: { savings: SavingsPoint[]; capitalTrend: CapitalPoint[]; accountRows: AccountMonth[]; savingsRate?: SavingsPoint[]; accounts: Account[] }) {
  const capitalReadout = useReadout(capitalTrend);
  const savingsReadout = useReadout(savings);
  const accountReadout = useReadout(accountRows);
  const positiveAccounts = wealthAccounts.filter((account) => account.balance > 0);
  const capitalAccountReadout = useReadout(positiveAccounts);
  const capitalAccountReadoutView = capitalAccountReadout.selected && <Box component="span" sx={{ color: colors[Math.max(0, positiveAccounts.indexOf(capitalAccountReadout.selected)) % colors.length], fontWeight: 600 }}>
    {`${capitalAccountReadout.selected.name}: ${euro(capitalAccountReadout.selected.balance)}`}
  </Box>;
  const [loans, setLoans] = useState<LoanSummary[]>([]);
  useEffect(() => {
    let cancelled = false;
    const initData = (window as Window & { Telegram?: { WebApp?: { initData?: string } } }).Telegram?.WebApp?.initData;
    fetch("/api/loans", { headers: initData ? { "X-Telegram-Init-Data": initData } : undefined })
      .then((response) => response.ok ? response.json() as Promise<{ loans?: LoanSummary[] }> : Promise.reject(new Error("loans_load_failed")))
      .then((data) => { if (!cancelled) setLoans(data.loans ?? []); })
      .catch(() => { if (!cancelled) setLoans([]); });
    return () => { cancelled = true; };
  }, []);
  const totalAssets = wealthAccounts.filter((account) => account.balance > 0).reduce((sum, account) => sum + account.balance, 0);
  const totalDebt = loans.filter((loan) => loan.status === "active").reduce((sum, loan) => sum + loan.residual_balance, 0);
  const netWorth = totalAssets - totalDebt;
  const rate = aggregateSavingsRate(savingsRate ?? []);
  const accountNames = [...new Set(accountRows.map((row) => row.account))];
  const rateRange = savingsRate && savingsRate.length > 0
    ? savingsRate.length === 1
      ? readoutForPeriod({ periodKey: String(savingsRate[0].period_key ?? savingsRate[0].month), periodLabel: String(savingsRate[0].period_label ?? savingsRate[0].month), isPartial: Boolean(savingsRate[0].is_partial) })
      : formatCompactPeriodRange(
        readoutForPeriod({ periodKey: String(savingsRate[0].period_key ?? savingsRate[0].month), periodLabel: String(savingsRate[0].period_label ?? savingsRate[0].month), isPartial: Boolean(savingsRate[0].is_partial) }),
        readoutForPeriod({ periodKey: String(savingsRate.at(-1)?.period_key ?? savingsRate.at(-1)?.month), periodLabel: String(savingsRate.at(-1)?.period_label ?? savingsRate.at(-1)?.month), isPartial: Boolean(savingsRate.at(-1)?.is_partial) }),
      )
    : "Periodo selezionato";
  const accountData = [...new Set(accountRows.map((row) => row.month))].map((month) => ({ month, ...Object.fromEntries(accountNames.map((account) => [account, accountRows.filter((row) => row.month === month && row.account === account).reduce((sum, row) => sum + row.amount, 0)])) }));
  return <>
    <AdvancedChartCard title="Andamento del capitale" explanation="Saldo totale dei conti attivi su Expensum nel periodo selezionato." readout={capitalReadout.selected && `${readoutForPeriod({ periodKey: String(capitalReadout.selected.period_key ?? capitalReadout.selected.month), periodLabel: String(capitalReadout.selected.period_label ?? capitalReadout.selected.month), isPartial: Boolean(capitalReadout.selected.is_partial) })}: ${euro(capitalReadout.selected.total)}`}>
      <ResponsiveContainer width="100%" height={220}><LineChart data={capitalTrend} margin={{ top: 16, right: 16, bottom: 4, left: 4 }}><XAxis dataKey="month" /><YAxis width={72} tickFormatter={(value) => `€${value}`} /><Line {...animationProps} dataKey="total" stroke="#5FC4CB" strokeWidth={2} dot={clickableDot(capitalReadout.selectIndex)} /></LineChart></ResponsiveContainer>
    </AdvancedChartCard>
    <AdvancedChartCard title="Entrate, uscite e risparmio mensile" explanation="Entrate, uscite e risparmio netto del periodo selezionato. Calcolato su spese e entrate registrate." readout={savingsReadout.selected && `Risparmio netto · ${readoutForPeriod({ periodKey: String(savingsReadout.selected.period_key ?? savingsReadout.selected.month), periodLabel: String(savingsReadout.selected.period_label ?? savingsReadout.selected.month), isPartial: Boolean(savingsReadout.selected.is_partial) })}: ${euro(savingsReadout.selected.savings)}`}>
      <ResponsiveContainer width="100%" height={220}><BarChart data={savings}><XAxis dataKey="month" /><YAxis tickFormatter={(value) => `€${value}`} /><Bar {...animationProps} dataKey="income" fill="#16A34A" onClick={(datum) => savingsReadout.selectWhere((point) => point.month === datum.payload?.month)} /><Bar {...animationProps} dataKey="expenses" fill="#E66767" onClick={(datum) => savingsReadout.selectWhere((point) => point.month === datum.payload?.month)} /><Bar {...animationProps} dataKey="savings" fill="#5FC4CB" onClick={(datum) => savingsReadout.selectWhere((point) => point.month === datum.payload?.month)} /></BarChart></ResponsiveContainer>
      <ColorLegend items={[{ label: "Entrate", color: "#16A34A" }, { label: "Uscite", color: "#E66767" }, { label: "Risparmio", color: "#5FC4CB" }]} />
    </AdvancedChartCard>
    {savingsRate && savingsRate.length > 0 && <AdvancedChartCard title="Tasso di risparmio" explanation="Percentuale di capitale (soldi) che sei riuscito a risparmiare nel periodo selezionato." readout={<><span style={{ display: "block" }}>Tasso del periodo: {rate.rate.toFixed(1)}%</span><span style={{ display: "block" }}>Risparmio netto del periodo: {euro(rate.savings)}</span></>}>
      <ResponsiveContainer width="100%" height={220}><BarChart data={[{ period: rateRange, rate: rate.rate }]}><XAxis dataKey="period" interval={0} tick={{ fontSize: 11 }} /><YAxis tickFormatter={(value) => `${value}%`} /><Bar {...animationProps} dataKey="rate" fill="#5FC4CB"><LabelList dataKey="rate" position="top" formatter={(value) => `${Number(value).toFixed(1)}%`} /></Bar></BarChart></ResponsiveContainer>
    </AdvancedChartCard>}
    <AdvancedChartCard title="Spesa mensile per conto" explanation="Totale di spesa mensile che hai registrato con Expensum nel periodo selezionato." readout={accountReadout.selected && `${readoutForPeriod({ periodKey: String(accountReadout.selected.period_key ?? accountReadout.selected.month), periodLabel: String(accountReadout.selected.period_label ?? accountReadout.selected.month), isPartial: Boolean(accountReadout.selected.is_partial) })} · ${accountReadout.selected.account}: ${euro(accountReadout.selected.amount)}`}>
      <ResponsiveContainer width="100%" height={220}><BarChart data={accountData}><XAxis dataKey="month" /><YAxis tickFormatter={(value) => `€${value}`} />{accountNames.map((account, index) => <Bar {...animationProps} key={account} dataKey={account} fill={colors[index % colors.length]} onClick={(datum) => { const selected = resolveAccountBarReadout(datum, account, accountRows); if (selected) accountReadout.selectIndex(accountRows.indexOf(selected)); }} />)}</BarChart></ResponsiveContainer>
      <ColorLegend items={accountNames.map((account, index) => ({ label: account, color: colors[index % colors.length] }))} />
    </AdvancedChartCard>
    <AdvancedChartCard title="Capitale per conto" explanation="Distribuzione del capitale sui conti che usi su Expensum. Include solo saldi positivi." readout={capitalAccountReadoutView}>
      {positiveAccounts.length === 0 ? <Empty label="Nessun dato disponibile" /> : <ResponsiveContainer width="100%" height={220}>
        <PieChart><Pie {...animationProps} data={positiveAccounts} dataKey="balance" nameKey="name" cx="50%" cy="50%" innerRadius={46} outerRadius={78} label={({ name }) => name} onClick={(_data, index) => capitalAccountReadout.selectIndex(resolvePieIndex(_data, index))}>{positiveAccounts.map((account, index) => <Cell key={account.name} fill={colors[index % colors.length]} />)}</Pie></PieChart>
      </ResponsiveContainer>}
    </AdvancedChartCard>
    <AdvancedChartCard title="Patrimonio netto" explanation="Capitale totale sui tuoi conti Expensum tenendo conto di debiti residui dei mutui e finanziamenti attivi." readout={`Patrimonio netto: ${euro(netWorth)}`}>
      <Box sx={{ minHeight: 220, display: "grid", alignContent: "center", gap: 1.25 }}>
        <Box sx={{ display: "flex", justifyContent: "space-between", gap: 2 }}><Typography variant="body2" color="text.secondary">Capitale sui conti</Typography><Typography variant="body2">{euro(totalAssets)}</Typography></Box>
        {totalDebt > 0 && <Box sx={{ display: "flex", justifyContent: "space-between", gap: 2 }}><Typography variant="body2" color="text.secondary">Debiti residui</Typography><Typography variant="body2" color="error.main">−{euro(totalDebt)}</Typography></Box>}
        <Box sx={{ display: "flex", justifyContent: "space-between", gap: 2, pt: 1, borderTop: "1px solid rgba(176,181,185,0.18)" }}><Typography variant="subtitle2" fontWeight={600}>Patrimonio netto</Typography><Typography variant="subtitle2" color="primary" fontWeight={600}>{euro(netWorth)}</Typography></Box>
      </Box>
    </AdvancedChartCard>
  </>;
}

function incomeCategoryName(operation: IncomeTransaction): string {
  const structuredCategory = typeof operation.income_category === "string"
    ? operation.income_category
    : operation.income_category?.name;
  return (structuredCategory || operation.income_type || "Altra entrata").trim() || "Altra entrata";
}

function IncomeCharts({ income, incomeCategories = [], incomeNature = [], incomeOperations = [] }: { income: SavingsPoint[]; incomeCategories?: IncomeCategorySummary[]; incomeNature?: IncomeNatureSummary[]; incomeOperations?: IncomeTransaction[] }) {
  const incomeReadout = useReadout(income);
  const categoryReadout = useReadout(incomeCategories);
  const natureReadout = useReadout(incomeNature);
  const [expandedCategory, setExpandedCategory] = useState<string | null>(null);
  const [expandedOperation, setExpandedOperation] = useState<number | null>(null);
  const [expandedNature, setExpandedNature] = useState<string | null>(null);
  const selectedCategory = categoryReadout.selected?.name;
  const categoryOperations = incomeOperations.filter((operation) =>
    incomeCategoryName(operation) === selectedCategory);
  const selectedNature = natureReadout.selected?.name;
  const natureOperations = incomeOperations.filter((operation) => {
    const operationCategory = incomeCategoryName(operation).toLocaleLowerCase();
    const category = incomeCategories.find((item) => item.name.trim().toLocaleLowerCase() === operationCategory);
    return (category?.recurring ?? false) === (selectedNature === "Ricorrenti");
  });
  const axisTick = { fill: "#F5F7F6", fontSize: 12 };
  const axisStyle = { stroke: "rgba(245,247,246,0.7)" };
  return <>
    <AdvancedChartCard title="Entrate mensili" explanation="Entrate registrate su Expensum nel periodo selezionato." readout={incomeReadout.selected && `${readoutForPeriod({ periodKey: String(incomeReadout.selected.period_key ?? incomeReadout.selected.month), periodLabel: String(incomeReadout.selected.period_label ?? incomeReadout.selected.month), isPartial: Boolean(incomeReadout.selected.is_partial) })}: ${euro(incomeReadout.selected.income)}`}>
      <ResponsiveContainer width="100%" height={235}><BarChart data={income} margin={{ top: 24, right: 8, bottom: 4, left: 4 }}><XAxis dataKey="month" tick={axisTick} axisLine={axisStyle} tickLine={axisStyle} /><YAxis tick={axisTick} axisLine={axisStyle} tickLine={axisStyle} tickFormatter={(value) => `€${value}`} /><Bar {...animationProps} dataKey="income" fill="#16A34A" onClick={(datum) => incomeReadout.selectWhere((point) => point.month === datum.payload?.month)}><LabelList dataKey="income" position="top" fill="#F5F7F6" fontSize={12} formatter={(value) => euro(Number(value))} /></Bar></BarChart></ResponsiveContainer>
    </AdvancedChartCard>
    <AdvancedChartCard title="Entrate per categoria" explanation="Distribuzione delle entrate registrate su Expensum per categoria nel periodo selezionato (ad es.: Stipendio o Bonus lavorativo). Usa la categoria strutturata e, solo per record legacy, il tipo di entrata." readout={categoryReadout.selected && <Box>
      <Box component="button" onClick={() => setExpandedCategory(expandedCategory === selectedCategory ? null : selectedCategory ?? null)} sx={{ all: "unset", display: "flex", alignItems: "center", gap: 1, width: "100%" }}>
        {categoryReadout.selected.name}: {euro(categoryReadout.selected.total)} · {categoryReadout.selected.count} entrat{categoryReadout.selected.count === 1 ? "a" : "e"}<ChevronDown size={16} style={{ transform: expandedCategory === selectedCategory ? "rotate(180deg)" : undefined }} />
      </Box>
      {expandedCategory === selectedCategory && <Box sx={{ mt: 1, display: "grid", gap: .75 }}>
        {categoryOperations.map((operation, index) => { const operationId = operation.id ?? index; return <Box key={operationId} component="button" onClick={() => setExpandedOperation(expandedOperation === operationId ? null : operationId)} sx={{ all: "unset", display: "flex", justifyContent: "space-between", gap: 1, flexWrap: "wrap", color: "inherit", fontSize: "0.9rem" }}>
          <span>{operation.name || selectedCategory}</span><span>{euro(operation.amount)} · {formatDisplayDate(operation.date)} <ChevronDown size={14} style={{ verticalAlign: "middle", transform: expandedOperation === operationId ? "rotate(180deg)" : undefined }} /></span>
          {expandedOperation === operationId && <Box component="span" sx={{ width: "100%", pl: 1, color: "text.secondary", fontSize: "0.82rem" }}>Categoria: {incomeCategoryName(operation)}{operation.account ? ` · Conto: ${operation.account}` : ""}</Box>}
        </Box>; })}
      </Box>}
    </Box>}>
      {incomeCategories.length === 0 ? <Empty label="Nessuna entrata disponibile" /> : <ResponsiveContainer width="100%" height={Math.max(180, incomeCategories.length * 42)}>
        <BarChart data={incomeCategories} margin={{ top: 12, right: 8, bottom: 18, left: 4 }} onClick={categoryReadout.select}>
          <XAxis dataKey="name" interval={0} axisLine={axisStyle} tickLine={axisStyle} tick={{ ...axisTick, fontSize: 11 }} />
          <YAxis tick={axisTick} axisLine={axisStyle} tickLine={axisStyle} tickFormatter={(value) => `€${value}`} />
          <Bar {...animationProps} dataKey="total" fill="#5FC4CB" radius={[0, 5, 5, 0]} onClick={(datum) => categoryReadout.selectWhere((category) => category.name === datum.payload?.name)} />
        </BarChart>
      </ResponsiveContainer>}
    </AdvancedChartCard>
    <AdvancedChartCard title="Entrate ricorrenti vs straordinarie" explanation="Quali sono le entrate ricorrenti e quelle straordinarie nel periodo selezionato. Le entrate ricorrenti sono presenti in almeno due mesi distinti del periodo; le altre sono straordinarie. È una classificazione basata sulla ricorrenza osservata, non sul tipo fiscale." readout={natureReadout.selected && <Box>
      <Box component="button" onClick={() => setExpandedNature(expandedNature === selectedNature ? null : selectedNature ?? null)} sx={{ all: "unset", display: "flex", alignItems: "center", gap: 1, width: "100%" }}>
        {natureReadout.selected.name}: {euro(natureReadout.selected.total)} · {natureReadout.selected.count} entrat{natureReadout.selected.count === 1 ? "a" : "e"}<ChevronDown size={16} style={{ transform: expandedNature === selectedNature ? "rotate(180deg)" : undefined }} />
      </Box>
      {expandedNature === selectedNature && <Box sx={{ mt: 1, display: "grid", gap: .75 }}>
        {natureOperations.map((operation, index) => { const operationId = (operation.id ?? index) + 100000; return <Box key={operationId} component="button" onClick={() => setExpandedOperation(expandedOperation === operationId ? null : operationId)} sx={{ all: "unset", display: "flex", justifyContent: "space-between", gap: 1, flexWrap: "wrap", color: "inherit", fontSize: "0.9rem" }}>
          <span>{operation.name || (typeof operation.income_category === "string" ? operation.income_category : operation.income_category?.name) || operation.income_type || "Entrata"}</span><span>{euro(operation.amount)} · {formatDisplayDate(operation.date)} <ChevronDown size={14} style={{ verticalAlign: "middle", transform: expandedOperation === operationId ? "rotate(180deg)" : undefined }} /></span>
          {expandedOperation === operationId && <Box component="span" sx={{ width: "100%", pl: 1, color: "text.secondary", fontSize: "0.82rem" }}>Categoria: {typeof operation.income_category === "string" ? operation.income_category : operation.income_category?.name || operation.income_type || "Altra entrata"}{operation.account ? ` · Conto: ${operation.account}` : ""}</Box>}
        </Box>; })}
      </Box>}
    </Box>}>
      {incomeNature.length === 0 ? <Empty label="Nessuna entrata disponibile" /> : <ResponsiveContainer width="100%" height={190}>
        <BarChart data={incomeNature} margin={{ top: 18, right: 12, bottom: 4, left: 4 }} onClick={natureReadout.select}>
          <XAxis dataKey="name" interval={0} tick={axisTick} axisLine={axisStyle} tickLine={axisStyle} />
          <YAxis tick={axisTick} axisLine={axisStyle} tickLine={axisStyle} tickFormatter={(value) => `€${value}`} />
          <Bar {...animationProps} dataKey="total" radius={[5, 5, 0, 0]} onClick={(datum) => natureReadout.selectWhere((item) => item.name === datum.payload?.name)}>
            {incomeNature.map((item) => <Cell key={item.name} fill={item.name === "Ricorrenti" ? "#5FC4CB" : "#F0A93E"} />)}
          </Bar>
        </BarChart>
      </ResponsiveContainer>}
    </AdvancedChartCard>
  </>;
}

/** Grafici dell'area Analisi dettagliate, senza overlay al passaggio del mouse. */
function ExpenseCharts({ categories, merchants, months = 1, grouped = true, onGroupedChange, onReload }: Props & { months?: number; grouped?: boolean; onGroupedChange?: (grouped: boolean) => void; onReload?: () => void }) {
  const router = useRouter();
  const [labelFix, setLabelFix] = useState<{ mode: LabelFixMode; target: LabelFixTarget } | null>(null);
  const [toast, setToast] = useState<string | null>(null);
  // Le richieste di operazioni possono accavallarsi (click rapidi, refetch dopo una
  // correzione): senza request-id una risposta vecchia sovrascriverebbe quella nuova.
  const operationsRequestId = useRef(0);
  const history = useMemo(() => buildTopCategoryHistory(categories), [categories]);
  const treemapReadout = useReadout(history);
  const [trendFocus, setTrendFocus] = useState<string | undefined>();
  const [expandedCategories, setExpandedCategories] = useState<Set<string>>(new Set());
  const trend = useMemo(() => buildCategoryTrendFocus(categories, trendFocus), [categories, trendFocus]);
  const trendReadout = useReadout(trend.focus.points);
  const merchantReadout = useReadout(merchants);
  const selectedMerchant = merchantReadout.selected;
  const [expandedMerchant, setExpandedMerchant] = useState<string | null>(null);
  const [merchantOperations, setMerchantOperations] = useState<MerchantOperation[]>([]);
  const [operationsLoading, setOperationsLoading] = useState(false);
  const [expandedOperationId, setExpandedOperationId] = useState<number | null>(null);
  const toggleMerchant = async (name: string) => {
    merchantReadout.selectWhere((merchant) => merchant.name === name);
    if (expandedMerchant === name) {
      setExpandedMerchant(null);
      setMerchantOperations([]);
      setExpandedOperationId(null);
      return;
    }
    setExpandedMerchant(name);
    setExpandedOperationId(null);
    setOperationsLoading(true);
    const requestId = ++operationsRequestId.current;
    try {
      const today = new Date();
      const start = new Date(today.getFullYear(), today.getMonth() - months + 1, 1);
      const params = new URLSearchParams({
        limit: "500",
        start: start.toISOString().slice(0, 10),
        end: today.toISOString().slice(0, 10),
      });
      const initData = (window as Window & { Telegram?: { WebApp?: { initData?: string } } }).Telegram?.WebApp?.initData;
      const response = await fetch(`/api/analytics/transactions?${params}`, {
        headers: initData ? { "X-Telegram-Init-Data": initData } : undefined,
      });
      if (!response.ok) throw new Error("transactions_load_failed");
      const data = await response.json() as { transactions?: MerchantOperation[] };
      if (requestId !== operationsRequestId.current) return;
      setMerchantOperations((data.transactions ?? []).filter((operation) => (grouped ? (operation.normalized_name ?? operation.name) : operation.name) === name));
    } catch {
      if (requestId === operationsRequestId.current) setMerchantOperations([]);
    } finally {
      if (requestId === operationsRequestId.current) setOperationsLoading(false);
    }
  };
  const merchantReadoutView = selectedMerchant && <Box sx={{ display: "grid", gap: 1 }}>
    <Box
      component="button"
      type="button"
      aria-expanded={expandedMerchant === selectedMerchant.name}
      aria-label={`${expandedMerchant === selectedMerchant.name ? "Chiudi" : "Apri"} le operazioni di ${selectedMerchant.name}`}
      onClick={() => void toggleMerchant(selectedMerchant.name)}
      sx={{ display: "inline-flex", alignItems: "center", gap: 0.5, width: "fit-content", p: 0, border: 0, background: "transparent", color: "inherit", font: "inherit", textAlign: "left", outline: "none" }}
    >
      <span>{`${selectedMerchant.name}: ${selectedMerchant.total.toLocaleString("it-IT", { style: "currency", currency: "EUR" })} · ${selectedMerchant.count} operazioni`}</span>
      <ChevronDown size={17} aria-hidden="true" style={{ transform: expandedMerchant === selectedMerchant.name ? "rotate(180deg)" : "none" }} />
    </Box>
    {expandedMerchant === selectedMerchant.name && <Box sx={{ display: "grid", gap: 0.5, pl: 1, borderLeft: "2px solid rgba(95,196,203,0.35)" }}>
      {operationsLoading && <Typography variant="caption" color="text.secondary">Caricamento operazioni…</Typography>}
      {!operationsLoading && merchantOperations.length === 0 && <Typography variant="caption" color="text.secondary">Nessuna operazione trovata nel periodo.</Typography>}
      {!operationsLoading && merchantOperations.map((operation) => <Box key={operation.id} sx={{ display: "grid", gap: 0.5 }}>
        <Box
          component="button"
          type="button"
          aria-expanded={expandedOperationId === operation.id}
          onClick={() => setExpandedOperationId((current) => current === operation.id ? null : operation.id)}
          sx={{ display: "grid", gridTemplateColumns: "minmax(0, 1fr) auto", gap: 1, alignItems: "center", width: "100%", p: 0, border: 0, background: "transparent", color: "inherit", font: "inherit", textAlign: "left", outline: "none", py: 0.5, "&:hover": { color: "primary.main" } }}
        >
          <span style={{ display: "inline-flex", alignItems: "center", gap: 4 }}>
            {operation.name}
            <ChevronDown size={15} aria-hidden="true" style={{ transform: expandedOperationId === operation.id ? "rotate(180deg)" : "none" }} />
          </span>
          <span>{euro(operation.amount)}</span>
        </Box>
        {expandedOperationId === operation.id && <Box sx={{ display: "grid", gap: 0.25, pl: 1, pb: 0.5, color: "text.secondary" }}>
          <Typography variant="caption">Data: {formatDisplayDate(operation.date)}</Typography>
          <Typography variant="caption">Categoria: {operation.category || "—"}</Typography>
          <Typography variant="caption">Conto: {operation.account || "—"}</Typography>
          <Box component="a" href={`/spazio?tab=expenses&search=${encodeURIComponent(operation.name)}&expense=${operation.id}`} sx={{ color: "primary.main", fontSize: "0.75rem", textDecoration: "none", width: "fit-content" }}>
            Apri in Gestisci
          </Box>
        </Box>}
      </Box>)}
      {selectedMerchant.cluster_id != null && <>
        <Divider sx={{ my: 0.5 }} />
        <Box sx={{ display: "flex", gap: 1 }}>
          <Button size="small" sx={{ minHeight: 44 }} onClick={() => setLabelFix({ mode: "merge", target: { id: selectedMerchant.cluster_id as number, anchorText: selectedMerchant.name, categoryId: selectedMerchant.category_id ?? null } })}>Unisci</Button>
          <Button size="small" sx={{ minHeight: 44 }} onClick={() => setLabelFix({ mode: "split", target: { id: selectedMerchant.cluster_id as number, anchorText: selectedMerchant.name, categoryId: selectedMerchant.category_id ?? null } })}>Dividi</Button>
        </Box>
      </>}
    </Box>}
  </Box>;
  const categoryBuckets = useMemo(() => {
    const buckets = new Map<string, { label: string; months: number }>();
    categories.forEach((row) => {
      const key = row.period_key ?? row.period_label ?? row.month ?? "";
      if (!buckets.has(key)) {
        buckets.set(key, {
          label: row.period_label ?? row.month ?? key,
          months: row.months_included ?? 1,
        });
      }
    });
    return [...buckets.entries()].sort(([left], [right]) => left.localeCompare(right)).map(([, bucket]) => bucket);
  }, [categories]);
  const categoryPeriod = categoryBuckets.length > 1
    ? `${categoryBuckets[0].label} – ${categoryBuckets.at(-1)?.label}`
    : categoryBuckets[0]?.label ?? "Periodo selezionato";
  const categoryPeriodDisplay = categoryBuckets.length > 1
    ? formatCompactPeriodRange(categoryBuckets[0].label, categoryBuckets.at(-1)?.label ?? categoryBuckets[0].label)
    : categoryPeriod;
  const categoryTotal = categories.reduce((sum, row) => sum + row.amount, 0);
  const categoryMonths = categoryBuckets.reduce((sum, bucket) => sum + bucket.months, 0);
  const categoryMonthlyAverage = categoryTotal / Math.max(categoryMonths, 1);
  const trendTotal = trend.focus.points.reduce((sum, point) => sum + point.amount, 0);
  const trendActiveMonths = trend.focus.points.reduce(
    (sum, point) => sum + (point.amount > 0 ? point.monthsIncluded : 0),
    0,
  );
  const trendAverage = trendTotal / Math.max(trendActiveMonths, 1);
  const showTrendAverage = categoryMonths > 1;
  const merchantYAxisWidth = Math.min(
    168,
    Math.max(112, Math.max(...merchants.map((merchant) => merchant.name.length), 0) * 6.2 + 12),
  );

  return (
    <>
      <AdvancedChartCard title="Distribuzione di spesa per categoria" explanation="Totale delle uscite nel periodo selezionato, raggruppate per categoria. Include le spese attribuite alle tue categorie ed esclude le entrate." readout={treemapReadout.selected && `${treemapReadout.selected.name}: ${euro(treemapReadout.selected.total)}`}>
        {history.length === 0 ? <Empty label="Nessun dato disponibile" /> : (
          <ResponsiveContainer width="100%" height={220}>
            <Treemap {...animationProps} data={history.map((item, index) => ({ ...item, size: item.total, fill: colors[index % colors.length] }))} dataKey="size" aspectRatio={4 / 3} stroke="#1C363D" onClick={(node) => treemapReadout.selectIndex(resolveTreemapIndex(node, history))} content={({ x, y, width, height, fill }) => (
              <rect x={Number(x)} y={Number(y)} width={Number(width)} height={Number(height)} fill={String(fill)} rx={4} stroke="none" />
            )} />
          </ResponsiveContainer>
        )}
        <Typography variant="body2" color="text.secondary" sx={{ display: "block", mt: 1, lineHeight: 1.55 }}>
          Da {categoryPeriodDisplay} hai speso <Box component="strong" sx={{ color: "text.primary", fontWeight: 600 }}>{euro(categoryTotal)}</Box>{categoryMonths > 1 && <>, con una spesa mensile media di <Box component="strong" sx={{ color: "text.primary", fontWeight: 600 }}>{euro(categoryMonthlyAverage)}</Box></>}.
        </Typography>
        <Typography variant="caption" color="text.secondary" sx={{ display: "block", mt: 1 }}>Categorie di spesa</Typography>
        <Box sx={{ display: "grid", gap: 1.25, mt: 0.75 }} aria-label="Categorie di spesa">
          {history.map((item, index) => <Box key={item.name} sx={{ display: "grid", gap: 0.35, minWidth: 0 }}>
            <Box
              component="button"
              type="button"
              aria-expanded={expandedCategories.has(item.name)}
              onClick={() => {
                setExpandedCategories((current) => {
                  const next = new Set(current);
                  if (next.has(item.name)) next.delete(item.name);
                  else next.add(item.name);
                  return next;
                });
              }}
              sx={{ display: "flex", alignItems: "center", gap: 0.75, minWidth: 0, width: "100%", p: 0, border: 0, background: "transparent", color: "inherit", font: "inherit", textAlign: "left", outline: "none" }}
            >
              <Box component="span" sx={{ width: 9, height: 9, borderRadius: "2px", backgroundColor: colors[index % colors.length], flexShrink: 0 }} />
              <Typography variant="caption" fontWeight={600} sx={{ minWidth: 0, overflowWrap: "anywhere", flex: 1 }}>{item.name}</Typography>
              <ChevronDown size={16} aria-hidden="true" style={{ flexShrink: 0, transform: expandedCategories.has(item.name) ? "rotate(180deg)" : "none" }} />
            </Box>
            {expandedCategories.has(item.name) && <>
              <Box sx={{ display: "grid", gridTemplateColumns: "minmax(0, 1fr) auto", gap: 1, pl: 2.25, alignItems: "baseline" }}>
                <Typography variant="caption" color="text.secondary">Totale periodo</Typography>
                <Typography variant="caption" color="text.secondary" sx={{ textAlign: "right", whiteSpace: "nowrap" }}>{euro(item.total)}</Typography>
              </Box>
              <Box sx={{ display: "grid", gridTemplateColumns: "minmax(0, 1fr) auto", gap: 1, pl: 2.25, alignItems: "baseline" }}>
                <Typography variant="caption" color="text.secondary">Media mensile</Typography>
                <Typography variant="caption" color="text.secondary" sx={{ textAlign: "right", whiteSpace: "nowrap" }}>{euro(item.monthlyAverage)}</Typography>
              </Box>
            </>}
          </Box>)}
        </Box>
      </AdvancedChartCard>

      <AdvancedChartCard title="Andamento categoria" explanation="Andamento di spesa nel periodo selezionato della categoria selezionata. La linea tratteggiata indica la media mensile della categoria nel periodo selezionato. Puoi cliccare sulle categorie per visualizzare il loro andamento. In basso puoi vedere una preview dell'andamento; se è presente un punto, ciò significa che quella categoria non ha ancora abbastanza dati per tracciare un andamento." readout={trendReadout.selected && categoryTrendReadout(trend.focus.name, trendReadout.selected, showTrendAverage ? trendAverage : undefined)}>
        {trend.focus.points.length === 0 ? <Empty label="Nessun dato disponibile" /> : (
          <>
            <ResponsiveContainer width="100%" height={220}>
              <LineChart data={trend.focus.points}>
                <XAxis dataKey="periodLabel" tick={{ fontSize: 11, fill: "#B0B5B9" }} />
                <YAxis tick={{ fontSize: 11, fill: "#B0B5B9" }} tickFormatter={(value) => `€${value}`} />
                {showTrendAverage && <ReferenceLine y={trendAverage} stroke="#F0A93E" strokeWidth={2} strokeDasharray="6 4" />}
                <Line {...animationProps} dataKey="amount" name={trend.focus.name} stroke="#5FC4CB" strokeWidth={2} dot={clickableDot(trendReadout.selectIndex)} />
              </LineChart>
            </ResponsiveContainer>
            <Box sx={{ display: "flex", flexWrap: "wrap", gap: 2, alignItems: "center", mt: 0.5 }} aria-label="Legenda andamento categoria">
              <Typography variant="caption" sx={{ color: "#5FC4CB", fontWeight: 600 }}>Spesa mensile</Typography>
              {showTrendAverage && <Box sx={{ display: "inline-flex", alignItems: "center", gap: 0.75 }}>
                <Box component="span" sx={{ width: 22, borderTop: "2px dashed #F0A93E" }} />
                <Typography variant="caption" sx={{ color: "#F0A93E", fontWeight: 600 }}>Media mensile del periodo</Typography>
              </Box>}
            </Box>
            <Box sx={{ display: "grid", gridTemplateColumns: { xs: "1fr", sm: "repeat(2, minmax(0, 1fr))" }, gap: 0.75, mt: 1.25, pt: 1.25, borderTop: "1px solid rgba(176,181,185,0.18)" }} aria-label="Categorie di supporto">
              {trend.supporting.map((series, index) => {
                const seriesColor = colors[index % colors.length];
                return <Box key={series.name} role="button" tabIndex={0} aria-label={`Mostra andamento di ${series.name}`} onClick={() => setTrendFocus(series.name)} onKeyDown={(event) => {
                  if (event.key === "Enter" || event.key === " ") {
                    event.preventDefault();
                    setTrendFocus(series.name);
                  }
                }} sx={{ display: "grid", gridTemplateColumns: "minmax(0, 1fr) auto", alignItems: "center", gap: 1, minWidth: 0, color: seriesColor, outline: "none" }}>
                <Typography variant="caption" sx={{ color: "inherit", minWidth: 0, overflowWrap: "anywhere" }}>{series.name}</Typography>
                <Sparkline points={series.points.map((point) => point.amount)} color={seriesColor} width={64} />
              </Box>;
              })}
            </Box>
          </>
        )}
      </AdvancedChartCard>

      {onGroupedChange && <LabelGroupingToggle grouped={grouped} onChange={onGroupedChange} />}
      <AdvancedChartCard title="Dove hai speso di più nel periodo selezionato" explanation={`Totale pagato per le principali voci di spesa nel periodo selezionato. Include le spese registrate su Expensum nel periodo, il numero di operazioni e i loro dettagli. ${GROUPING_DISCLAIMER}`} readout={merchantReadoutView}>
        {merchants.length === 0 ? <Empty label="Nessun dato disponibile" /> : (
          <ResponsiveContainer width="100%" height={Math.max(220, merchants.length * 30)}>
            <BarChart data={merchants} layout="vertical" margin={{ left: 8, right: 28 }}>
              <XAxis type="number" tickFormatter={(value) => `€${value}`} tick={{ fontSize: 11, fill: "#B0B5B9" }} />
              <YAxis
                type="category"
                dataKey="name"
                width={merchantYAxisWidth}
                interval={0}
                tick={({ x, y, payload }) => {
                  const name = String(payload?.value ?? "");
                  const merchantIndex = merchants.findIndex((merchant) => merchant.name === name);
                  const selectMerchant = () => merchantReadout.selectIndex(merchantIndex);
                  return <text
                    x={x}
                    y={y}
                    textAnchor="end"
                    fill="#B0B5B9"
                    fontSize={11}
                    role="button"
                    tabIndex={0}
                    aria-label={`Mostra dettaglio di ${name}`}
                    style={{ outline: "none" }}
                    onClick={selectMerchant}
                    onKeyDown={(event) => {
                      if (event.key === "Enter" || event.key === " ") {
                        event.preventDefault();
                        selectMerchant();
                      }
                    }}
                  >{name}</text>;
                }}
              />
              <Bar {...animationProps} dataKey="total" fill="#5FC4CB" radius={[0, 4, 4, 0]} onClick={(datum) => merchantReadout.selectWhere((merchant) => merchant.name === datum.payload?.name)} />
            </BarChart>
          </ResponsiveContainer>
        )}
      </AdvancedChartCard>

      <LabelFixDialog
        open={labelFix !== null}
        mode={labelFix?.mode ?? "merge"}
        target={labelFix?.target ?? null}
        months={months}
        initData={typeof window === "undefined" ? undefined : (window as Window & { Telegram?: { WebApp?: { initData?: string } } }).Telegram?.WebApp?.initData}
        onClose={() => setLabelFix(null)}
        onDone={(message) => {
          // La voce selezionata può non esistere più dopo la correzione: si chiude il
          // dettaglio aperto e si ricarica il grafico.
          operationsRequestId.current += 1;
          setExpandedMerchant(null);
          setMerchantOperations([]);
          setExpandedOperationId(null);
          setToast(message);
          onReload?.();
        }}
      />
      <Snackbar
        open={toast !== null}
        autoHideDuration={3000}
        onClose={() => setToast(null)}
        message={toast ?? ""}
        anchorOrigin={{ vertical: "bottom", horizontal: "center" }}
      />
    </>
  );
}

type AdvancedProps = Props & {
  mode?: "expenses" | "overview" | "income";
  months?: number;
  savings?: SavingsPoint[];
  capitalTrend?: CapitalPoint[];
  accountRows?: AccountMonth[];
  income?: SavingsPoint[];
  incomeCategories?: IncomeCategorySummary[];
  incomeNature?: IncomeNatureSummary[];
  incomeOperations?: IncomeTransaction[];
  savingsRate?: SavingsPoint[];
  /** Switch "raggruppa"/"per nome" delle voci di spesa: assente = nessuno switch. */
  grouped?: boolean;
  onGroupedChange?: (grouped: boolean) => void;
  /** Ricarica i dati dopo una correzione manuale del raggruppamento. */
  onReload?: () => void;
};

export default function AdvancedCharts({ mode = "expenses", savings = [], capitalTrend = [], accountRows = [], income = [], savingsRate = [], ...props }: AdvancedProps) {
  if (mode === "overview") return <OverviewCharts savings={savings} capitalTrend={capitalTrend} accountRows={accountRows} savingsRate={savingsRate} accounts={props.accounts} />;
    if (mode === "income") return <IncomeCharts income={income} incomeCategories={props.incomeCategories} incomeNature={props.incomeNature} incomeOperations={props.incomeOperations} />;
  return <ExpenseCharts {...props} />;
}
