import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

const source = readFileSync(new URL("./QuickCapture.tsx", import.meta.url), "utf8");
const shellSource = readFileSync(new URL("./ProtectedAppShell.tsx", import.meta.url), "utf8");

test("the composer is titled 'Registra un movimento'", () => {
  assert.match(source, /Registra un movimento/);
});

test("reuses the shared capture controller instead of duplicating API calls", () => {
  assert.match(source, /useExpenseCaptureFlow\(\{[\s\S]*?loadHistory: false/);
  // Nessuna chiamata diretta agli endpoint di acquisizione: passano tutte dal controller.
  assert.doesNotMatch(source, /fetch\("\/api\/chat\/(message|voice|photo|confirm)"/);
});

test("offers text, voice and photo capture in the same sheet", () => {
  assert.match(source, /Es\. 24 € al supermercato/);
  assert.match(source, /sendText\(/);
  assert.match(source, /toggleVoice\(/);
  assert.match(source, /sendPhoto\(/);
});

test("renders an accessible dialog with a labelled title and initial focus on the textarea", () => {
  assert.match(source, /aria-labelledby=/);
  assert.match(source, /autoFocus/);
  assert.match(source, /<Dialog|<Drawer/);
});

test("keeps the explicit confirmation of the chat: no save without the user acting", () => {
  assert.match(source, /confirm\(/);
  assert.match(source, /cancel\(/);
  assert.doesNotMatch(source, /saveDirect\(/);
});

test("after saving offers to record another movement or to open Gestisci", () => {
  assert.match(source, /Registrato/);
  assert.match(source, /Registra un altro/);
  assert.match(source, /Apri Gestisci/);
  assert.match(source, /reset\(\)/);
  // La rotta la decide la shell (`onOpenManage`), il composer resta agnostico.
  assert.match(source, /onOpenManage\(\)/);
  assert.match(shellSource, /router\.push\("\/spazio"\)/);
});

test("a non-financial command is not executed here: it points back to the chat", () => {
  assert.match(source, /Continua in Chat/);
  assert.match(source, /\/chat/);
});

test("closing with pending content asks for confirmation, an empty composer closes immediately", () => {
  assert.match(source, /Vuoi uscire\? Il movimento non è stato registrato\./);
});

test("send controls stay disabled while an upload is in flight", () => {
  assert.match(source, /disabled=\{[^}]*isLoading/);
});

test("keeps the chat features that would otherwise dead-end here", () => {
  // Categorizzazione adattiva: la domanda arriva dal controller, servono i bottoni.
  assert.match(source, /categoryPromotion && !msg\.categoryPromotionResolved/);
  assert.match(source, /resolveCategoryPromotion\(/);
  // Nessun conto configurato: stessa scorciatoia offerta dalla Chat.
  assert.match(source, /noAccountAction/);
  assert.match(source, /Vai ai Conti/);
});

test("keeps the AI disclosure visible, since the composer never shows the welcome message", () => {
  assert.match(source, /generate automaticamente con Mistral AI/);
});

test("exposes the bottom sheet as a modal dialog for screen readers", () => {
  assert.match(source, /role: "dialog"/);
  assert.match(source, /"aria-modal": true/);
});

test("the exit confirmation lives outside the scrollable area and takes focus", () => {
  assert.match(source, /role="alertdialog"/);
  assert.match(source, /keepEditingRef\.current\?\.focus\(\)/);
  assert.match(source, /className=\{styles\.exitConfirm\}/);
});

test("both navigations open the same composer state held by the shell", () => {
  assert.match(shellSource, /QuickCapture/);
  assert.match(shellSource, /onOpenCapture=\{/);
  // L'apertura non cambia rotta: nessun push del router legato al pulsante Registra.
  assert.doesNotMatch(shellSource, /onOpenCapture=\{\(\) => router\.push/);
});
