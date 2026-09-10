import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { join } from "node:path";
import test from "node:test";

test("uses annual data points and five-year ticks for the residual balance chart", () => {
  const source = readFileSync(join(process.cwd(), "src/app/mutuo/page.tsx"), "utf8");

  assert.match(
    source,
    /entry\.period % 12 === 0/,
  );
  assert.match(
    source,
    /const residualTicks = Array\.from\([\s\S]*index \* 60/,
  );
  assert.match(
    source,
    /<XAxis[\s\S]*ticks=\{residualTicks\}[\s\S]*label=\{\{[^}]*value: "Mesi"/,
  );
});

test("explains comparison scenarios for fixed and variable mortgage quotes", () => {
  const source = readFileSync(join(process.cwd(), "src/app/mutuo/MortgageSustainabilityPanel.tsx"), "utf8");

  assert.match(source, /Confronto tra preventivi/);
  assert.match(source, /Stress test di possibili revisioni del tasso/);
  assert.match(source, /Margine:/);
  assert.match(source, /result\.stress_scenarios\.length > 0/);

  const wizardSource = readFileSync(join(process.cwd(), "src/app/mutuo/LoanWizard.tsx"), "utf8");
  assert.match(wizardSource, /\{preview &&\s*\(\s*<MortgageSustainabilityPanel/);
  assert.doesNotMatch(wizardSource, /step === 1 && preview &&/);
});

test("derives the variable mortgage TAN from Euribor plus spread", () => {
  const source = readFileSync(join(process.cwd(), "src/app/mutuo/LoanWizard.tsx"), "utf8");

  assert.match(source, /const effectiveTan = form\.rate_type === "variabile"/);
  assert.match(source, /Number\(form\.euribor_current\) \|\| 0\) \+ \(Number\(form\.spread\) \|\| 0\)/);
});

test("lets the user save a simulation as a draft without making it mandatory", () => {
  const source = readFileSync(join(process.cwd(), "src/app/mutuo/LoanWizard.tsx"), "utf8");

  assert.match(source, /Salva bozza/);
  assert.match(source, /onClick=\{handleSave\}/);
});

test("uses the derived TAN in the sustainability simulation", () => {
  const source = readFileSync(join(process.cwd(), "src/app/mutuo/LoanWizard.tsx"), "utf8");

  assert.match(source, /tanAnnual:\s*effectiveTan/);
});

test("saves the sustainability choices in the simulation draft", () => {
  const wizardSource = readFileSync(join(process.cwd(), "src/app/mutuo/LoanWizard.tsx"), "utf8");
  const panelSource = readFileSync(join(process.cwd(), "src/app/mutuo/MortgageSustainabilityPanel.tsx"), "utf8");

  assert.match(wizardSource, /onDraftInputChange=\{handleDraftSustainabilityInputChange\}/);
  assert.match(wizardSource, /\.\.\.draftSustainabilityInput/);
  assert.match(panelSource, /onDraftInputChange\?\.\(/);
});

test("restores saved sustainability inputs when a draft is reopened", () => {
  const wizardSource = readFileSync(join(process.cwd(), "src/app/mutuo/LoanWizard.tsx"), "utf8");
  const panelSource = readFileSync(join(process.cwd(), "src/app/mutuo/MortgageSustainabilityPanel.tsx"), "utf8");

  assert.match(wizardSource, /initialSustainabilityInput/);
  assert.match(wizardSource, /monthly_income/);
  assert.match(wizardSource, /selected_category_ids/);
  assert.match(wizardSource, /initialDraftInput=\{draftSustainabilityInput\}/);
  assert.match(panelSource, /initialDraftInput/);
  assert.match(panelSource, /setIncome/);
  assert.match(panelSource, /setSelectedIds/);
});

test("shows saved mortgage drafts in the mortgage page", () => {
  const source = readFileSync(join(process.cwd(), "src/app/mutuo/page.tsx"), "utf8");

  assert.match(source, /\/api\/mortgage-simulations/);
  assert.match(source, /Bozze salvate/);
  assert.match(source, /Apri bozza/);
  assert.match(source, /Duplica bozza/);
  assert.match(source, /Elimina bozza/);
});

test("offers an accessible amortization table beside the mortgage charts", () => {
  const source = readFileSync(join(__dirname, "page.tsx"), "utf8");

  assert.match(source, /Piano di ammortamento/);
  assert.match(source, /<table/);
  assert.match(source, /Dettaglio mensile/);
  assert.equal((source.match(/<th scope="col">N\. rata<\/th>/g) ?? []).length, 2);
});

test("keeps mortgage layouts usable on the iPhone 16 Pro viewport", () => {
  const source = readFileSync(join(process.cwd(), "src/app/mutuo/page.tsx"), "utf8");
  const wizardSource = readFileSync(join(process.cwd(), "src/app/mutuo/LoanWizard.tsx"), "utf8");

  assert.match(source, /gridTemplateColumns:\s*\{\s*xs:\s*"1fr"/);
  assert.match(source, /overflowX:\s*"auto"/);
  assert.match(source, /minWidth:\s*0/);
  assert.match(wizardSource, /& \.MuiDialog-paper[\s\S]*m:\s*\{\s*xs:\s*0/);
  assert.match(wizardSource, /gridTemplateColumns:\s*\{\s*xs:\s*"1fr"/);
});

test("uses a flat mortgage chart tooltip without a glow effect", () => {
  const source = readFileSync(join(process.cwd(), "src/app/mutuo/page.tsx"), "utf8");

  assert.match(source, /const TOOLTIP_STYLE/);
  assert.match(source, /svg:focus/);
  assert.match(source, /svg \*:focus/);
});

test("gives mortgage charts an explicit height during initial layout", () => {
  const source = readFileSync(join(process.cwd(), "src/app/mutuo/page.tsx"), "utf8");

  assert.equal((source.match(/<ResponsiveContainer width=\"100%\" height=\{150\}/g) ?? []).length, 2);
});

test("keeps loan card headings and actions from collapsing on narrow screens", () => {
  const source = readFileSync(join(process.cwd(), "src/app/mutuo/page.tsx"), "utf8");

  assert.match(source, /CardHeader[\s\S]*titleTypographyProps=\{\{[^}]*minWidth:\s*0/);
  assert.match(source, /CardHeader[\s\S]*subheaderTypographyProps=\{\{[^}]*minWidth:\s*0/);
  assert.match(source, /CardHeader[\s\S]*action=\{[\s\S]*flexShrink:\s*0/);
});

test("wraps mortgage stress and category text instead of truncating it", () => {
  const source = readFileSync(join(process.cwd(), "src/app/mutuo/MortgageSustainabilityPanel.tsx"), "utf8");

  assert.match(source, /stress_scenarios\.map[\s\S]*overflowWrap:\s*"anywhere"/);
  assert.match(source, /label=\{category\.name\}[\s\S]*overflowWrap:\s*"anywhere"/);
});

test("keeps the buffer card readable and tappable on mobile", () => {
  const source = readFileSync(join(process.cwd(), "src/app/mutuo/page.tsx"), "utf8");

  assert.match(source, /minWidth:\s*0[\s\S]*Fondo cuscinetto/);
  assert.match(source, /Crea un obiettivo[\s\S]*width:\s*\{\s*xs:\s*"100%"/);
  assert.match(source, /Crea un obiettivo[\s\S]*minHeight:\s*44/);
});

test("keeps dashboard tables, actions and dialogs reachable on iPhone", () => {
  const source = readFileSync(join(process.cwd(), "src/app/mutuo/page.tsx"), "utf8");

  assert.match(source, /Scorri orizzontalmente per vedere tutte le colonne/);
  assert.match(source, /minHeight:\s*44/);
  assert.match(
    source,
    /\.MuiDialog-paper[\s\S]*maxHeight:\s*\{\s*xs:\s*"100%"/,
  );
});

test("wraps dashboard actions instead of overflowing on iPhone", () => {
  const source = readFileSync(join(process.cwd(), "src/app/mutuo/page.tsx"), "utf8");

  assert.match(
    source,
    /<Box sx=\{\{\s*maxWidth:\s*780,[\s\S]*width:\s*"100%"[\s\S]*boxSizing:\s*"border-box"/,
  );
  assert.match(
    source,
    /flex:\s*\{\s*xs:\s*"1 1 calc\(50% - 4px\)",\s*sm:\s*"initial"\s*\}/,
  );
  assert.match(source, /minWidth:\s*\{\s*xs:\s*0,\s*sm:\s*"auto"\s*\}/);
});

test("keeps wizard preview, sustainability fields and actions single-column on iPhone", () => {
  const wizard = readFileSync(join(process.cwd(), "src/app/mutuo/LoanWizard.tsx"), "utf8");
  const panel = readFileSync(join(process.cwd(), "src/app/mutuo/MortgageSustainabilityPanel.tsx"), "utf8");

  assert.match(wizard, /\.MuiDialog-paper[\s\S]*width:\s*\{\s*xs:\s*"100%"/);
  assert.match(wizard, /DialogContent sx=\{\{[\s\S]*minWidth:\s*0/);
  assert.match(wizard, /DialogActions sx=\{\{[\s\S]*minHeight:\s*44/);
  assert.match(panel, /gridTemplateColumns:\s*\{\s*xs:\s*"1fr"/);
  assert.match(panel, /minHeight:\s*44/);
  assert.match(panel, /flexWrap:\s*"wrap"/);
});

test("keeps sustainability panel from collapsing inside the mobile wizard", () => {
  const panel = readFileSync(join(process.cwd(), "src/app/mutuo/MortgageSustainabilityPanel.tsx"), "utf8");

  assert.match(panel, /<Card[\s\S]*flexShrink:\s*0/);
});

test("prefills empty sustainability fields once from the evaluate response", () => {
  const panel = readFileSync(join(process.cwd(), "src/app/mutuo/MortgageSustainabilityPanel.tsx"), "utf8");

  assert.match(panel, /prefill\?:/);
  assert.match(panel, /monthly_income/);
  assert.match(panel, /essential_monthly_expenses/);
  assert.match(panel, /monthly_savings_target/);
  assert.match(panel, /history_months/);
  assert.match(panel, /Spiega reddito precompilato/);
  assert.match(panel, /tutte le uscite presenti su Expensum/);
  assert.match(panel, /Spesa mensile osservata/);
  assert.match(panel, /prefillAppliedRef/);
  assert.match(panel, /prev\s*===\s*""/);
  assert.match(panel, /const prefill = data\.prefill/);
});

test("does not treat the empty sustainability defaults as a saved draft", () => {
  const panel = readFileSync(join(process.cwd(), "src/app/mutuo/MortgageSustainabilityPanel.tsx"), "utf8");

  assert.match(panel, /const hasDraftValues =/);
  assert.match(panel, /monthly_income != null/);
  assert.match(panel, /essential_monthly_expenses != null/);
  assert.match(panel, /monthly_savings_target != null/);
  assert.match(panel, /if \(hasDraftValues\) \{/);
});

test("prevents page scrolling from changing the mortgage TAN", () => {
  const wizard = readFileSync(join(process.cwd(), "src/app/mutuo/LoanWizard.tsx"), "utf8");

  assert.match(wizard, /label=\"TAN \(%\)\"[\s\S]*onWheel=\{\(event\) => \{ event\.preventDefault\(\); event\.currentTarget\.blur\(\); \}\}/);
  assert.match(wizard, /onTouchMove=\{\(event\) => event\.preventDefault\(\)\}/);
  assert.match(wizard, /touchAction: \"none\"/);
});

test("explains sustainability conclusions and calculated values with accessible info buttons", () => {
  const panel = readFileSync(join(process.cwd(), "src/app/mutuo/MortgageSustainabilityPanel.tsx"), "utf8");

  assert.match(panel, /from "@\/components\/InfoButton"/);
  assert.ok((panel.match(/<InfoButton/g) ?? []).length >= 8);
  assert.match(panel, /Affidabilità[\s\S]*InfoButton/);
  assert.match(panel, /Rata totale[\s\S]*InfoButton/);
  assert.match(panel, /Margine[\s\S]*InfoButton/);
  assert.match(panel, /Margine dopo il mutuo[\s\S]*InfoButton/);
  assert.match(panel, /scenarioTitle[\s\S]*InfoButton/);
});

test("delegates the sustainability evaluation call to the shared apiFetch client", () => {
  const panel = readFileSync(join(process.cwd(), "src/app/mutuo/MortgageSustainabilityPanel.tsx"), "utf8");

  assert.match(panel, /from "@\/lib\/api"/);
  assert.match(panel, /apiFetch<\{[\s\S]*?>\("\/api\/mortgage-simulations\/evaluate", \{ method: "POST"/);
  assert.match(panel, /setError\(apiErrorMessage\(cause, /);
  assert.doesNotMatch(panel, /response\.headers\.get\("content-type"\)/);
});
