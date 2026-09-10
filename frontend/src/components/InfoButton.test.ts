import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

test("opens the explanation from the info icon on click", () => {
  const source = readFileSync(new URL("./InfoButton.tsx", import.meta.url), "utf8");

  assert.match(source, /Popover/);
  assert.match(source, /onClick/);
  assert.match(source, /aria-expanded/);
  assert.match(source, /label \?\?/);
  assert.match(source, /explanation/);
});
