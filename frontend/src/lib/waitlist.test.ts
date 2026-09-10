import assert from "node:assert/strict";
import test from "node:test";

import { getReferralCode } from "./waitlist";

test("reads a referral code from the landing page query string", () => {
  assert.equal(getReferralCode("?ref=invite_42"), "invite_42");
  assert.equal(getReferralCode("?utm_source=instagram&ref=invite_42"), "invite_42");
});

test("ignores missing or empty referral codes", () => {
  assert.equal(getReferralCode("?utm_source=instagram"), null);
  assert.equal(getReferralCode("?ref="), null);
});
