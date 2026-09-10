import assert from "node:assert/strict";
import test from "node:test";

import { isAtomNearViewport } from "./atomViewport";

test("loads the atom before the section enters the viewport", () => {
  assert.equal(isAtomNearViewport(1200, 900, 500), true);
  assert.equal(isAtomNearViewport(1450, 900, 500), false);
});

test("keeps the atom loaded while the section is passing the viewport", () => {
  assert.equal(isAtomNearViewport(-500, 900, 500), true);
  assert.equal(isAtomNearViewport(-1501, 900, 500), false);
});
