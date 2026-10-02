import { strict as assert } from "node:assert";
import { test } from "node:test";
import {
  acceptAllOptionalConsents,
  DEFAULT_OPTIONAL_CONSENTS,
  GOAL_CODES,
  rejectAllOptionalConsents,
  toggleGoal,
} from "./onboardingModel";

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

test("defaults less sensitive consents on and training consents off", () => {
  assert.deepEqual(DEFAULT_OPTIONAL_CONSENTS, {
    product_analytics: true,
    marketing_email: true,
    algorithm_improvement: false,
    structured_text_usage: false,
    structured_voice_usage: false,
    ocr_text_usage: false,
  });
});

test("accept all enables every optional consent", () => {
  assert.deepEqual(acceptAllOptionalConsents(), {
    product_analytics: true,
    marketing_email: true,
    algorithm_improvement: true,
    structured_text_usage: true,
    structured_voice_usage: true,
    ocr_text_usage: true,
  });
});
