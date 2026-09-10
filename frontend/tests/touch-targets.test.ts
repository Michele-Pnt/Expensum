import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

const read = (path: string) => readFileSync(new URL(path, import.meta.url), "utf8");

test("sets chat primary actions to a 44px touch target", () => {
  const css = read("../src/app/chat/page.module.css");
  assert.match(css, /\.quickChip\s*\{[\s\S]*?min-height:\s*44px/);
  assert.match(css, /\.confirmBtn\s*\{[\s\S]*?min-height:\s*44px/);
});

test("sets calendar navigation and selectable days to a 44px touch target", () => {
  const css = read("../src/app/calendario/calendario.module.css");
  assert.match(css, /\.navButton\s*\{[\s\S]*?width:\s*44px/);
  assert.match(css, /\.cell\s*\{[\s\S]*?min-width:\s*44px/);
});

test("sets Analytics tabs and Space row actions to at least 44px", () => {
  const analytics = read("../src/app/analytics/page.tsx");
  const spazio = read("../src/app/spazio/page.tsx");
  assert.match(analytics, /minHeight:\s*44/);
  assert.match(spazio, /width:\s*44,\s*height:\s*44/);
});
