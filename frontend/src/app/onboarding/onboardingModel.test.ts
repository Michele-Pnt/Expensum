import { strict as assert } from "node:assert";
import { test } from "node:test";
import { GOAL_CODES, rejectAllOptionalConsents, toggleGoal } from "./onboardingModel";

test("exposes the approved onboarding goals", () => {
  assert.deepEqual(GOAL_CODES, [
    "cashflow_control",
    "budget",
    "emergency_fund",
    "savings_goal",
    "increase_savings",
  ]);
});

test("keeps selected goals in explicit priority order", () => {
  const next = toggleGoal(["budget", "emergency_fund"], "cashflow_control");
  assert.deepEqual(next, ["budget", "emergency_fund", "cashflow_control"]);
});

test("reject all clears every optional consent", () => {
  assert.deepEqual(rejectAllOptionalConsents(), {
    product_analytics: false,
    marketing_email: false,
    algorithm_improvement: false,
    structured_text_usage: false,
    structured_voice_usage: false,
    ocr_text_usage: false,
  });
});
