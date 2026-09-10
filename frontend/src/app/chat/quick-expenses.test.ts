import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { createRequire } from "node:module";
import test from "node:test";

const require = createRequire(import.meta.url);
require.extensions[".css"] = () => undefined;

const source = readFileSync(new URL("./page.tsx", import.meta.url), "utf8");
const controllerSource = readFileSync(
  new URL("../../features/expense-capture/useExpenseCaptureFlow.ts", import.meta.url),
  "utf8",
);

test("keeps dashboard mini stats out of the chat layout", () => {
  assert.doesNotMatch(source, /miniStats/);
  assert.doesNotMatch(source, /statsBar/);
});

test("loads quick expenses dynamically and keeps their chips visible on the welcome screen", () => {
  assert.match(
    source,
    /fetch\("\/api\/chat\/quick-expenses", \{ credentials: "same-origin", headers \}\)/,
  );
  assert.match(
    source,
    /setQuickExpenses\(Array\.isArray\(data\?\.quick_expenses\) \? data\.quick_expenses : \[\]\)/,
  );

  const quickActions = source.slice(source.indexOf("{/* ── Quick actions:"));
  assert.match(quickActions, /className=\{styles\.quickRow\}/);
  assert.doesNotMatch(quickActions, /!showWelcome\s*&&/);
});

test("refreshes quick expenses only after a transaction was saved", () => {
  assert.match(source, /const refreshQuickExpenses = useCallback\(async \(\) => \{/);
  // Il salvataggio vive nel controller condiviso: la chat si riallinea tramite
  // onSaved, che scatta solo quando il movimento è stato davvero registrato.
  assert.match(source, /onSaved: \(result\) => \{\s*if \(!result\.saved\) return;\s*void refreshQuickExpenses\(\);/);
  assert.match(controllerSource, /if \(data\.saved\) \{/);
  assert.match(source, /const requestId = \+\+quickExpensesRequestRef\.current;/);
  assert.match(source, /if \(requestId === quickExpensesRequestRef\.current\) \{/);
});

test("quick expense chips open a 2-step modal instead of drafting a chat message", () => {
  assert.match(source, /const handleQuickExpense = useCallback\(\(quickExpense: QuickExpense\) => \{/);
  assert.match(source, /step: "amount", amount: "",/);
  assert.match(source, /accountId: null, accounts: null, accountsLoading: false,/);
  // Il tap normale (non una pressione prolungata) apre il modale, rilevato via
  // pointer events per distinguerlo dal drag-and-drop di riordino.
  assert.match(source, /handleQuickExpense\(quickExpense\);/);
  // Niente più chiamata a Mistral per una spesa rapida: nessuna scrittura in inputText/chat.
  assert.doesNotMatch(source, /setInputText\(draft\.inputText\)/);
});

test("account is never preselected: step 2 loads accounts as one-tap buttons, no dropdown", () => {
  assert.match(source, /const proceedFromAmountStep = useCallback\(async \(\) => \{/);
  assert.match(source, /fetch\("\/api\/space\/accounts", \{/);
  assert.match(source, /className=\{styles\.quickModalAccountRow\}/);
  assert.doesNotMatch(source, /accountId: quickExpense\.account_id/);
});

test("tapping an account both selects it and submits immediately, no separate 'Registra' button", () => {
  assert.match(source, /onClick=\{\(\) => void submitQuickExpense\(acc\.id\)\}/);
  assert.doesNotMatch(source, /Registra<\/button>/);
});

test("quick expense submit reuses the shared capture controller (same /api/chat/confirm flow, same chat summary bubble)", () => {
  assert.match(source, /const submitQuickExpense = useCallback\(async \(accountId: string\) => \{/);
  assert.match(source, /await saveDirect\(\{/);
  assert.match(controllerSource, /fetch\("\/api\/chat\/confirm", \{/);
  assert.match(source, /type: "expense",/);
  assert.match(source, /name: current\.expense\.name,/);
  assert.match(source, /category: current\.expense\.category,/);
  assert.match(source, /\}, \{ account_id: accountId \}\);/);
  // Non deve chiamare l'endpoint diretto: il riepilogo/tracking/gamification
  // devono passare dallo stesso percorso del resto della chat.
  assert.doesNotMatch(source, /fetch\("\/api\/space\/expenses"/);
});

test("quick expense modal rejects a missing or non-positive amount before moving to the account step", () => {
  assert.match(
    source,
    /const isValidQuickAmount = \(amount: string\): boolean => \{/,
  );
  assert.match(source, /if \(!isValidQuickAmount\(prev\.amount\)\) return \{ \.\.\.prev, error: "Inserisci un importo valido\." \};/);
});

test("quick actions have a visible header explaining what they are, separated from the composer", () => {
  const quickActions = source.slice(source.indexOf("{/* ── Quick actions:"), source.indexOf("{/* ── Input Bar"));
  assert.match(quickActions, /Spese rapide/);
  assert.match(quickActions, /className=\{styles\.quickInfoBtn\}/);
  assert.match(quickActions, /className=\{styles\.quickSection\}/);
  // Sempre visibile (anche a 0 bottoni), per poterne creare uno personalizzato.
  assert.doesNotMatch(quickActions, /\{quickExpenses\.length > 0 &&/);
});

test("info popover explains that only the first button is automatic, the rest are user-created", () => {
  assert.match(source, /Il primo bottone è la spesa che fai più spesso/);
  assert.match(source, /Gli altri li crei tu/);
});

test("a '+' button opens a form to create a custom shortcut with user-chosen fields", () => {
  assert.match(source, /const openNewShortcutModal = useCallback\(async \(\) => \{/);
  assert.match(source, /className=\{styles\.quickAddBtn\}/);
  assert.match(source, /fetch\("\/api\/space\/categories", \{/);
  assert.match(source, /const submitNewShortcut = useCallback\(async \(\) => \{/);
  assert.match(source, /fetch\("\/api\/chat\/quick-expenses\/custom", \{/);
});

test("custom shortcuts can be removed; the automatic one cannot", () => {
  assert.match(source, /const deleteShortcut = useCallback\(async \(id: number\) => \{/);
  assert.match(source, /fetch\(`\/api\/chat\/quick-expenses\/custom\/\$\{id\}`, \{/);
  assert.match(source, /quickExpense\.source === "custom" && quickExpense\.id != null &&/);
});

test("a shortcut with a preset account registers immediately after the amount, skipping the account step", () => {
  assert.match(
    source,
    /if \(quickExpenseModal && isValidQuickAmount\(quickExpenseModal\.amount\) && quickExpenseModal\.expense\.account_id\) \{/,
  );
  assert.match(source, /await submitQuickExpense\(quickExpenseModal\.expense\.account_id\);/);
});

test("delete 'x' is hidden until a long-press enters edit mode, never shown on the automatic chip", () => {
  assert.match(source, /quickEditMode && quickExpense\.source === "custom" && quickExpense\.id != null && \(/);
  assert.doesNotMatch(source, /\{quickExpense\.source === "custom" && quickExpense\.id != null && \(\s*<button/);
});

function sliceFunction(fnStartPattern: RegExp): string {
  const start = source.search(fnStartPattern);
  assert.notEqual(start, -1, `pattern not found: ${fnStartPattern}`);
  const rest = source.slice(start);
  // Taglia al prossimo `const x = useCallback(` di primo livello dopo l'inizio,
  // così le asserzioni sotto restano scoperte solo dal corpo della funzione che
  // stiamo testando, non da qualunque `}, 500);`/`method: "PUT"` nel resto del file.
  const next = rest.slice(20).search(/\n  const \w+ = useCallback\(/);
  return next === -1 ? rest : rest.slice(0, next + 20);
}

test("a 500ms long-press on a chip enters edit mode via pointer events (touch-compatible, not native drag)", () => {
  const fn = sliceFunction(/const handleChipPointerDown = useCallback\(/);
  assert.match(fn, /}, 500\);/);
  assert.doesNotMatch(source, /draggable=\{true\}/);
  assert.doesNotMatch(source, /onDragStart=/);
  // La cattura del puntatore avviene subito in pointerdown (su currentTarget, il
  // wrapper stabile), non dentro il timeout — altrimenti un rilascio del dito
  // fuori dall'elemento prima dei 500ms lascia il timer vivo e la modalità
  // modifica scatta da sola più tardi, a dito già staccato.
  assert.match(fn, /e\.currentTarget\.setPointerCapture\(e\.pointerId\)/);
});

test("dragging a custom chip reorders it via 2D hit-testing against every other chip's rect (works across wrapped rows)", () => {
  const fn = sliceFunction(/const handleChipPointerMove = useCallback\(/);
  // Confronto solo su clientX romperebbe il riordino quando i bottoni vanno a
  // capo (flex-wrap): il "vicino nell'ordine" può stare su un'altra riga, a una
  // X molto più piccola. Qui si cerca il chip il cui rettangolo contiene
  // davvero (clientX, clientY), non solo si confronta il centro orizzontale.
  assert.match(fn, /e\.clientX >= r\.left && e\.clientX <= r\.right && e\.clientY >= r\.top && e\.clientY <= r\.bottom/);
  assert.match(fn, /next\.splice\(currentIdx, 1\);/);
  assert.match(fn, /next\.splice\(targetIdx, 0, draggingChipId\);/);
});

test("releasing after a drag persists the new order to the backend, skipping the call if nothing changed", () => {
  const fn = sliceFunction(/const persistShortcutOrder = useCallback\(async \(order: number\[\]\) => \{/);
  assert.match(fn, /fetch\("\/api\/chat\/quick-expenses\/custom\/reorder", \{/);
  assert.match(fn, /method: "PUT",/);

  const pointerUpFn = sliceFunction(/const handleChipPointerUp = useCallback\(/);
  assert.match(pointerUpFn, /orderChanged/);
  assert.match(pointerUpFn, /if \(orderChanged\) void persistShortcutOrder\(finalOrder\);/);
});

test("a 'Fatto' button exits edit mode; the '+' button is hidden while editing", () => {
  assert.match(source, /className=\{styles\.quickDoneBtn\}/);
  assert.match(source, /onClick=\{exitQuickEditMode\}/);
});
