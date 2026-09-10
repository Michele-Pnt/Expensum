import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

test("keeps the conversation area fluid on wide screens", () => {
  const css = readFileSync(new URL("./page.module.css", import.meta.url), "utf8");
  const messagesInner = css.match(/\.messagesInner\s*\{[\s\S]*?\n\}/)?.[0] ?? "";

  assert.doesNotMatch(messagesInner, /max-width\s*:/);
  assert.match(messagesInner, /padding:\s*16px clamp\(20px, 5vw, 96px\) 8px/);
});

test("keeps contextual destination cards available above an active conversation", () => {
  const source = readFileSync(new URL("./page.tsx", import.meta.url), "utf8");
  const css = readFileSync(new URL("./page.module.css", import.meta.url), "utf8");

  assert.match(source, /contextCards/);
  assert.match(source, /Hai speso/);
  assert.match(source, /Categoria top/);
  assert.match(source, /Budget rimasto/);
  assert.match(source, /analytics\/categories-expense\?months=1/);
  assert.match(source, /analytics\/budget-status/);
  assert.match(source, /financialSummaryRequestRef/);
  assert.match(source, /buildExpenseAnalyticsHref/);
  assert.match(source, /tab=plan/);
  assert.match(source, /\/spazio/);
  assert.equal((source.match(/className=\{styles\.contextCardAction\}/g) ?? []).length, 3);
  assert.match(source, /ChevronRight/);
  assert.doesNotMatch(css, /\.contextCard small \{ display: none; \}/);
});
