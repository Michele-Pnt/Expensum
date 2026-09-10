import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

const feedbackPage = readFileSync(
  new URL("../src/app/feedback/page.tsx", import.meta.url),
  "utf8"
);

test("submits feedback only through the form submit event", () => {
  assert.match(feedbackPage, /<form className=\{styles\.form\} onSubmit=\{handleSubmit\}>/);
  assert.doesNotMatch(feedbackPage, /<form[^>]*onClick=/);
});

test("keeps the feedback textarea associated with its visible label", () => {
  assert.match(feedbackPage, /<label[^>]*htmlFor="feedback-message"/);
  assert.match(feedbackPage, /<textarea[\s\S]*id="feedback-message"/);
});
