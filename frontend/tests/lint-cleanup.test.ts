import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

const read = (path: string) => readFileSync(new URL(path, import.meta.url), "utf8");

test("uses Next Image for local brand assets", () => {
  for (const path of [
    "../src/app/[locale]/come-funziona-moneo/page.tsx",
    "../src/app/[locale]/mutuo/MutuoCalculatorClient.tsx",
    "../src/components/legal/LegalChrome.tsx",
  ]) {
    assert.doesNotMatch(read(path), /<img\s/);
  }
});

test("keeps hook dependencies explicit without obsolete suppressions", () => {
  const reportPage = read("../src/app/reports/page.tsx");
  const tourContext = read("../src/context/TourContext.tsx");
  const tourOverlay = read("../src/components/TourOverlay.tsx");

  assert.doesNotMatch(reportPage, /eslint-disable-next-line react-hooks\/exhaustive-deps/);
  assert.doesNotMatch(tourContext, /eslint-disable-next-line react-hooks\/exhaustive-deps/);
  assert.match(tourOverlay, /\[isActive, currentStep, step, measureTarget, cleanupPrevElement\]/);
});
