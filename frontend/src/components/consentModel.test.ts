import { strict as assert } from "node:assert";
import { test } from "node:test";
import { mergeConsentState } from "./consentModel";

test("server withdrawal forces analytics consent off", () => {
  const next = mergeConsentState(
    {
      product_analytics: true,
      marketing_email: false,
      algorithm_improvement: false,
      structured_text_usage: false,
      structured_voice_usage: false,
      ocr_text_usage: false,
    },
    { product_analytics: false, marketing_email: false },
  );
  assert.equal(next.product_analytics, false);
});
