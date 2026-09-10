import assert from "node:assert/strict";
import test from "node:test";

import { getHowScreenType } from "./howItWorksScreens";

test("maps each how-it-works step to a real product screen", () => {
  assert.deepEqual(
    [0, 1, 2, 3].map(getHowScreenType),
    ["chat", "analysis", "dashboard", "report"],
  );
});

test("falls back to the chat screen for an unknown step", () => {
  assert.equal(getHowScreenType(99), "chat");
});
