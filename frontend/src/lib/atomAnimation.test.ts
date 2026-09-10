import assert from "node:assert/strict";
import test from "node:test";

import {
  ATOM_IDLE_TIME_SCALE,
  getIdleAtomAnimationNames,
} from "./atomAnimation";

test("keeps orbital idle animation clips and excludes the camera clip", () => {
  const names = [
    "Pivot_CameraAction.002",
    "Pivot_Luce_RotanteAction.006",
    "PivotSpin_01Action.007",
    "PivotWobble_01Action.001",
  ];

  assert.deepEqual(getIdleAtomAnimationNames(names), [
    "Pivot_Luce_RotanteAction.006",
    "PivotSpin_01Action.007",
  ]);
});

test("uses a deliberately slow, constant idle playback rate", () => {
  assert.equal(ATOM_IDLE_TIME_SCALE, 0.28);
});
