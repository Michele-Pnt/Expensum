import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";
import type { BarRectangleItem } from "recharts";
import {
  categoryTrendReadout,
  resolveAccountBarReadout,
  resolvePieIndex,
  resolveTreemapIndex,
} from "./components/AdvancedCharts";
import { aggregateSavingsRate } from "./components/AdvancedCharts";
import { readoutForPeriod } from "./advancedViewModels";

const pageSource = () => readFileSync(new URL("./page.tsx", import.meta.url), "utf8");
const chartSource = () => readFileSync(new URL("./components/AdvancedCharts.tsx", import.meta.url), "utf8");
const cardSource = () => readFileSync(new URL("./components/AdvancedChartCard.tsx", import.meta.url), "utf8");
const backendSource = () => readFileSync(new URL("../../../../src/dashboard/blueprints/analytics_routes.py", import.meta.url), "utf8");

test("removes the advanced Lista tab and links to Gestisci", () => {
  const source = pageSource();
  assert.doesNotMatch(source, /> Lista/);
  assert.match(source, /Apri Gestisci/);
  assert.doesNotMatch(source, /Il mio Spazio/);
});

test("does not use Recharts tooltip or active selection props in advanced charts", () => {
  const source = chartSource();
  assert.doesNotMatch(source, /<Tooltip/);
  assert.doesNotMatch(source, /activeShape|activeDot|activeBar|cursor=/);
});

test("renders an InfoButton on each advanced chart card", () => {
  const source = cardSource();
  assert.ok((source.match(/<InfoButton/g) ?? []).length >= 1);
});

test("preserves backend period metadata when adapting category rows", () => {
  assert.match(pageSource(), /period_key:\s*row\.period_key \?\? row\.month/);
  assert.match(pageSource(), /period_label:\s*row\.period_label \?\? row\.month/);
});

test("keeps Pro history within 24 months and uses quarterly Auto beyond 12", () => {
  const source = pageSource();
  assert.match(source, /Auto/);
  assert.match(source, /months <= 12/);
  assert.match(source, /months <= 12 \? "monthly" : "quarterly"/);
  assert.match(source, /isPro \? 24 : 6/);
  assert.doesNotMatch(source, /isPro \? 60 : 6/);
});

test("advanced data interactions expose persistent readouts without chart overlays", () => {
  const source = chartSource();
  assert.match(source, /onClick=.*treemapReadout/);
  assert.match(source, /onClick=.*accountReadout/);
  assert.match(source, /readout=/);
  assert.match(source, /resolveTreemapIndex/);
  assert.match(source, /resolvePieIndex/);
  assert.match(source, /ReferenceLine y=\{trendAverage\}/);
});

test("keeps dumbbell rows keyboard-operable without a pointer cursor", () => {
  const source = chartSource();
  assert.doesNotMatch(source, /cursor:\s*["']pointer/);
  assert.match(source, /role="button"/);
  assert.match(source, /onKeyDown/);
  assert.match(source, /tabIndex=\{0\}/);
});

test("maps Recharts Treemap and Pie callback payloads to readout indexes", () => {
  assert.equal(resolveTreemapIndex({ name: "Casa" }, [{ name: "Cibo" }, { name: "Casa" }]), 1);
  assert.equal(resolvePieIndex({ name: "Conto" }, 2), 2);
});

test("uses the exact merchant title and actionable space copy", () => {
  assert.match(chartSource(), /Dove hai speso di più nel periodo selezionato/);
  assert.match(pageSource(), /Apri Gestisci/);
});

test("models income analytics as categories, never sources", () => {
  const charts = chartSource();
  const page = pageSource();
  assert.match(charts, /Entrate per categoria/);
  assert.doesNotMatch(charts, /Entrate per fonte|fonte dell'entrata|IncomeSource|incomeSources/);
  assert.doesNotMatch(page, /incomeSources|bySource/);
});

test("keeps every Legacy advanced tab on compliant chart components", () => {
  const source = pageSource();
  const legacy = source.slice(source.indexOf("export function LegacyAnalyticsPage"));
  assert.doesNotMatch(legacy, /<(?:ChartCard|CapitalTrendChart|SavingsChart|SavingsRateChart|MonthlyByAccountChart|IncomeChart|WealthPieChart|NetWorthSummary|CategoryPieChart|CategoryHistoryChart|CategoryAvgChart|TopMerchantsChart|MonthComparisonChart)\b/);
  assert.doesNotMatch(legacy, /<Tooltip\b|<Legend\b|active(?:Shape|Dot|Bar)=/);
  assert.match(legacy, /<AdvancedCharts[\s\S]*mode="overview"/);
  assert.match(legacy, /<AdvancedCharts[\s\S]*mode="income"/);
});

test("uses weighted savings-rate display from aggregate income and expenses", () => {
  assert.deepEqual(aggregateSavingsRate([
    { month: "gen", income: 100, expenses: 50, savings: 50, rate: 50 },
    { month: "feb", income: 900, expenses: 0, savings: 900, rate: 100 },
  ]), { income: 1000, expenses: 50, savings: 950, rate: 95 });
});

test("keeps the aggregation selector at the 44px touch target", () => {
  assert.match(pageSource(), /advanced-granularity-label[\s\S]*minHeight:\s*44/);
});

test("allows Free category aggregation while retaining Pro-only weekly behavior", () => {
  const source = backendSource();
  assert.match(source, /requested_granularity = request\.args\.get\("granularity", "monthly"\)/);
  assert.match(source, /plan_type == "pro" and requested_granularity == "weekly"/);
});

test("maps the real Bar callback datum to its explicitly selected account series", () => {
  const datum: BarRectangleItem = {
    value: 42,
    payload: { month: "feb 26", Casa: 42, Carta: 19 },
    x: 0,
    y: 0,
    width: 10,
    height: 42,
    parentViewBox: { x: 0, y: 0, width: 100, height: 100 },
    tooltipPosition: { x: 5, y: 42 },
    stackedBarStart: 0,
    originalDataIndex: 1,
  };

  assert.deepEqual(resolveAccountBarReadout(datum, "Casa", [
    { month: "gen 26", account: "Casa", amount: 10 },
    { month: "feb 26", account: "Casa", amount: 42 },
    { month: "feb 26", account: "Carta", amount: 19 },
  ]), { month: "feb 26", account: "Casa", amount: 42 });
});

test("labels a partial annual category-trend bucket as current year", () => {
  assert.match(
    categoryTrendReadout("Casa", {
      periodKey: "2026",
      periodLabel: "2026",
      isPartial: true,
      monthsIncluded: 8,
      amount: 400,
    }),
    /Casa:.*2026 · anno in corso$/,
  );
});

test("renders partial-period metadata and direct series mappings", () => {
  const charts = chartSource();
  assert.equal(readoutForPeriod({ periodLabel: "2026", isPartial: true }), "2026 · anno in corso");
  assert.match(charts, /readoutForPeriod/);
  assert.match(charts, /Entrate.*Uscite.*Risparmio/);
  assert.match(charts, /account.*account/i);
});

test("does not render a zero savings-rate card for Free and explains budget data cards", () => {
  const page = pageSource();
  assert.doesNotMatch(page, /savingsRate=\{isPro && savingsRate \? savingsRate\.savings_rate : \[\]\}/);
  assert.match(page, /savingsRate\.savings_rate\.length > 0/);
  assert.match(page, /BudgetGaugeList[\s\S]*InfoButton/);
});
