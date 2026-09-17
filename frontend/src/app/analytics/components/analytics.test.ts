import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

const navigationSource = () => readFileSync(new URL("./AnalyticsNavigation.tsx", import.meta.url), "utf8");
const periodSource = () => readFileSync(new URL("./AnalyticsPeriodPicker.tsx", import.meta.url), "utf8");
const experienceSource = () => readFileSync(new URL("./AnalyticsExperience.tsx", import.meta.url), "utf8");
const plannerSource = () => readFileSync(new URL("./AnalyticsPlanner.tsx", import.meta.url), "utf8");

test("exposes the three mobile-first analytics destinations", () => {
  const source = navigationSource();

  assert.match(source, /Oggi/);
  assert.match(source, /Esplora/);
  assert.match(source, /Pianifica/);
  assert.match(source, /aria-current/);
});

test("uses semantic periods rather than a numeric months slider", () => {
  const source = periodSource();

  assert.match(source, /Questo mese/);
  assert.match(source, /Ultimi 3 mesi/);
  assert.match(source, /Anno in corso/);
  assert.doesNotMatch(source, /<Slider/);
});

test("places the period picker below navigation only for Explorer", () => {
  const source = experienceSource();

  assert.match(source, /<AnalyticsNavigation[\s\S]*destination === "explore" && \([\s\S]*<AnalyticsPeriodPicker/);
});

test("uses natural-language cards in Today instead of a pacing chart", () => {
  const source = readFileSync(new URL("./AnalyticsToday.tsx", import.meta.url), "utf8");

  assert.match(source, /Stima di fine mese/);
  assert.match(source, /Stai spendendo più del mese scorso/);
  assert.doesNotMatch(source, /AreaChart/);
  assert.doesNotMatch(source, /Il ritmo del mese/);
  assert.match(source, /Due cose da seguire/);
});

test("renders the approved monthly summary and an accessible savings comparison", () => {
  const source = readFileSync(new URL("./AnalyticsToday.tsx", import.meta.url), "utf8");

  assert.match(source, /Budget disponibile/);
  assert.match(source, /Uscite totali/);
  assert.match(source, /Entrate totali/);
  assert.match(source, /Risparmio mensile/);
  assert.match(source, /aria-expanded=\{showSavingsComparison\}/);
  assert.match(source, /minHeight: 44/);
  assert.match(source, /ArrowUpRight/);
  assert.match(source, /ArrowDownRight/);
});

test("omits insight cards when their data is unavailable", () => {
  const source = readFileSync(new URL("./AnalyticsToday.tsx", import.meta.url), "utf8");

  assert.match(source, /projection &&/);
  assert.match(source, /changes\.length > 0/);
});

test("keeps the budget summary card free from explanatory captions", () => {
  const source = readFileSync(new URL("./AnalyticsToday.tsx", import.meta.url), "utf8");

  assert.doesNotMatch(source, /summary\.statusLabel/);
  assert.match(source, /Il budget rimasto per questo mese\./);
  assert.match(source, /Il totale delle uscite registrate nel mese in corso\./);
});

test("provides an accessible label for the compact savings comparison", () => {
  const source = readFileSync(new URL("./AnalyticsToday.tsx", import.meta.url), "utf8");

  assert.match(source, /const savingsComparisonLabel/);
  assert.match(source, /aria-label=\{savingsComparisonLabel\}/);
  assert.match(source, /Risparmio migliore rispetto al mese scorso/);
  assert.match(source, /Risparmio peggiore rispetto al mese scorso/);
});

test("places explanatory info buttons next to every Analytics card title", () => {
  const today = readFileSync(new URL("./AnalyticsToday.tsx", import.meta.url), "utf8");
  const explorer = readFileSync(new URL("./AnalyticsExplorer.tsx", import.meta.url), "utf8");
  const planner = readFileSync(new URL("./AnalyticsPlanner.tsx", import.meta.url), "utf8");
  const experience = readFileSync(new URL("./AnalyticsExperience.tsx", import.meta.url), "utf8");

  assert.match(today, /import InfoButton/);
  assert.match(today, /explanation="Combiniamo l'andamento giornaliero delle spese/);
  assert.match(explorer, /import InfoButton/);
  assert.match(planner, /import InfoButton/);
  assert.match(planner, /Budget del mese/);
  assert.match(planner, /mese in corso/);
  assert.match(experience, /import InfoButton/);
});

test("lets Explorer switch dimension and open contextual operations", () => {
  const source = readFileSync(new URL("./AnalyticsExplorer.tsx", import.meta.url), "utf8");
  const experience = readFileSync(new URL("./AnalyticsExperience.tsx", import.meta.url), "utf8");

  assert.match(source, /Categorie/);
  assert.match(source, /Voci/);
  assert.match(source, /Conti/);
  assert.match(source, /onSelect/);
  assert.match(experience, /const choose = .*setDestination\("explore"\)/);
});

test("expands transactions inside the selected explorer row without a separate detail card", () => {
  const explorer = readFileSync(new URL("./AnalyticsExplorer.tsx", import.meta.url), "utf8");
  const experience = readFileSync(new URL("./AnalyticsExperience.tsx", import.meta.url), "utf8");

  assert.match(explorer, /Collapse/);
  assert.match(explorer, /aria-expanded/);
  assert.match(explorer, /transactionsLoading/);
  assert.doesNotMatch(experience, /Vedi operazioni/);
});

test("keeps charts out of Today", () => {
  const source = readFileSync(new URL("./AnalyticsToday.tsx", import.meta.url), "utf8");

  assert.doesNotMatch(source, /recharts|AreaChart|ResponsiveContainer/);
});

test("removes browser focus outlines from read-only charts across the webapp", () => {
  const theme = readFileSync(new URL("../../../theme/theme.ts", import.meta.url), "utf8");
  const legacyAnalytics = readFileSync(new URL("../page.tsx", import.meta.url), "utf8");
  const charts = legacyAnalytics.match(/<(?:AreaChart|BarChart|LineChart|ComposedChart|PieChart)\b[^>]*>/g) ?? [];

  assert.doesNotMatch(theme, /recharts-wrapper:focus/);
  assert.match(theme, /recharts-surface g\[tabindex="-1"\]:focus/);
  assert.ok(charts.length > 0);
  assert.ok(charts.every((chart) => chart.includes("accessibilityLayer={false}")));
});

test("keeps chart values in tooltips without visual hover overlays", () => {
  const chartSources = [
    readFileSync(new URL("../page.tsx", import.meta.url), "utf8"),
    readFileSync(new URL("./AnalyticsToday.tsx", import.meta.url), "utf8"),
    readFileSync(new URL("../../mutuo/page.tsx", import.meta.url), "utf8"),
    readFileSync(new URL("../../../components/ReportContent.tsx", import.meta.url), "utf8"),
  ];

  const tooltips = chartSources.flatMap((source) => source.match(/<Tooltip\b[^>]*\/>/g) ?? []);
  const pies = chartSources.flatMap((source) => source.match(/<Pie\b[^>]*>/g) ?? []);
  const cartesianSeries = chartSources.flatMap((source) => source.match(/<(?:Area|Line)\b[^>]*>/g) ?? []);
  const bars = chartSources.flatMap((source) => source.match(/<Bar\b[^>]*>/g) ?? []);

  assert.ok(tooltips.length > 0);
  assert.ok(tooltips.every((tooltip) => tooltip.includes("cursor={false}")));
  assert.ok(pies.length > 0);
  assert.ok(pies.every((pie) => pie.includes("activeShape={false}")));
  assert.ok(cartesianSeries.length > 0);
  assert.ok(cartesianSeries.every((series) => series.includes("activeDot={false}")));
  assert.ok(bars.length > 0);
  assert.ok(bars.every((bar) => bar.includes("activeBar={false}")));
});

test("keeps planner actionable when a budget is unavailable", () => {
  const source = plannerSource();

  assert.match(source, /Crea un budget/);
  assert.match(source, /Non ora/);
  assert.doesNotMatch(source, /filter:\s*["']blur/);
});

test("loads two-month history only for current-period comparisons", () => {
  const source = experienceSource();

  assert.match(source, /categories-expense\?months=2/);
  assert.match(source, /period === "current"/);
  assert.match(source, /buildSpendingChanges/);
  assert.match(source, /changes=\{changes\}/);
});

test("loads the general monthly budget from preferences for every plan", () => {
  const source = experienceSource();

  assert.match(source, /\/api\/user\/preferences/);
  assert.doesNotMatch(source, /overview\.plan_type === "pro" \? await getJson<[^>]+>\("\/api\/user\/preferences"\)/);
  assert.match(source, /monthlyBudget: preferences\.monthly_budget/);
});

test("uses compact responsive budget language", () => {
  const source = plannerSource();

  assert.match(source, /Budget e previsione di fine mese/);
  assert.match(source, /flexDirection=\{\{ xs: "column", sm: "row" \}\}/);
});

test("guards responsive analytics layouts and safe long labels", () => {
  const today = readFileSync(new URL("./AnalyticsToday.tsx", import.meta.url), "utf8");
  const explorer = readFileSync(new URL("./AnalyticsExplorer.tsx", import.meta.url), "utf8");
  const planner = plannerSource();

  assert.match(planner, /flexDirection=\{\{ xs: "column", sm: "row" \}\}/);
  assert.match(planner, /minWidth: 0, overflowWrap: "anywhere"/);
  // La riga è flex, non una griglia a colonne fisse: con una colonna importo a
  // minimo rigido (era minmax(9rem, auto)) su schermi stretti il nome veniva
  // schiacciato e spezzato lettera per lettera ("Bol/let/ta/luc/e//ga/s").
  // L'invariante da difendere: il nome può restringersi, l'importo no.
  assert.match(explorer, /flex: 1, minWidth: 0, overflowWrap: "anywhere"/);
  assert.match(explorer, /whiteSpace="nowrap" sx=\{\{ flexShrink: 0 \}\}/);
  assert.doesNotMatch(explorer, /minmax\(9rem/);
  assert.match(explorer, /minWidth: 0, overflowWrap: "anywhere"/g);
  assert.ok((explorer.match(/minWidth: 0, overflowWrap: "anywhere"/g) ?? []).length >= 2);
  assert.match(today, /overflowWrap: "anywhere"/);
});

test("keeps Analytics API mapping and current-only projection explicit", () => {
  const source = readFileSync(new URL("./AnalyticsExperience.tsx", import.meta.url), "utf8");

  assert.match(source, /setState\(\{[\s\S]*categories: categories\.by_category,[\s\S]*comparisons: comparisons\.by_category,/);
  assert.match(source, /state\.categories\.map/);
  assert.match(source, /state\?\.comparisons \?\?/);
  assert.match(source, /destination === "today" \? 2 : months/);
  assert.match(source, /monthEndForecast: overview\.month_end_forecast/);
  assert.match(source, /buildMonthEndProjection\(\{ currentNet: summary\.monthlySavings, forecast: state\?\.monthEndForecast/);
  assert.doesNotMatch(source, /<AnalyticsToday[^>]*\bsavings=/);
  assert.doesNotMatch(source, /<AnalyticsToday[^>]*\bperiod=/);
});

test("calculates the projection end date from the current calendar month", () => {
  const today = readFileSync(new URL("./AnalyticsToday.tsx", import.meta.url), "utf8");

  assert.match(today, /new Date\(today\.getFullYear\(\), today\.getMonth\(\) \+ 1, 0\)\.getDate\(\)/);
  assert.doesNotMatch(today, /Stima al 31 \{monthName\}/);
});

test("explains the projection formula, period and exclusions", () => {
  const today = readFileSync(new URL("./AnalyticsToday.tsx", import.meta.url), "utf8");

  assert.match(today, /andamento giornaliero delle spese/);
  assert.match(today, /abbonamenti futuri confermati/);
  assert.match(today, /previsione unificata delle entrate residue/);
  assert.match(today, /Entrate previste residue/);
  assert.match(today, /Bilancio di oggi/);
});

test("a deep link can open Esplora on the Voci lens with names ungrouped", () => {
  const source = experienceSource();
  // La destinazione va letta all'inizializzazione dello stato: leggerla in un
  // effetto farebbe partire il primo caricamento col raggruppamento sbagliato.
  assert.match(source, /const deepLink = readDeepLink\(\);/);
  assert.match(source, /useState<ExplorerDimension>\(deepLink\.dimension\)/);
  assert.match(source, /useState<boolean \| null>\(deepLink\.grouped\)/);
  assert.match(source, /grouped: group === "0" \? false : group === "1" \? true : null/);
});
