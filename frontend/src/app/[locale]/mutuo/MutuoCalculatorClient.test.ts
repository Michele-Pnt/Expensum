import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { join } from "node:path";
import test from "node:test";

test("keeps the public mortgage calculator results readable on iPhone 16 Pro", () => {
  const source = readFileSync(
    join(process.cwd(), "src/app/[locale]/mutuo/MutuoCalculatorClient.tsx"),
    "utf8",
  );

  assert.match(
    source,
    /display:\s*"flex"[\s\S]*flexDirection:\s*\{\s*xs:\s*"column"/,
  );
  assert.match(source, /overflowWrap:\s*"anywhere"/);
  assert.match(source, /width:\s*\{\s*xs:\s*"100%"/);
  assert.match(source, /minHeight:\s*\{\s*xs:\s*44/);
});

test("keeps the return-to-site link reachable on mobile", () => {
  const source = readFileSync(
    join(process.cwd(), "src/app/[locale]/mutuo/MutuoCalculatorClient.tsx"),
    "utf8",
  );

  assert.match(source, /minHeight:\s*44[\s\S]*backToSite/);
  assert.match(source, /display:\s*"inline-flex"[\s\S]*backToSite/);
});
