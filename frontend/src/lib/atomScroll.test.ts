import assert from "node:assert/strict";
import test from "node:test";

import { getAtomStep } from "./atomScroll";

test("maps normalized progress across all seven atom steps", () => {
  assert.equal(getAtomStep(0, 7), 0);
  assert.equal(getAtomStep(0.14, 7), 0);
  assert.equal(getAtomStep(0.15, 7), 1);
  assert.equal(getAtomStep(0.5, 7), 3);
  assert.equal(getAtomStep(0.999, 7), 6);
  assert.equal(getAtomStep(1, 7), 6);
});

test("clamps progress outside the normalized range", () => {
  assert.equal(getAtomStep(-2, 7), 0);
  assert.equal(getAtomStep(3, 7), 6);
});

test("rejects an invalid step count", () => {
  assert.throws(() => getAtomStep(0.5, 0), /positive integer/);
  assert.throws(() => getAtomStep(0.5, 2.5), /positive integer/);
});
