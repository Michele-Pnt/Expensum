import assert from "node:assert/strict";
import test from "node:test";

import { marketingContent } from "./marketingContent";

test("keeps English marketing copy aligned with the Italian source", () => {
  assert.equal(
    marketingContent.en.how.title,
    "From your voice to a clearer choice."
  );
  assert.equal(
    marketingContent.en.features.items[0].text,
    "A simple overview to see where your money goes and recognize your spending habits."
  );
  assert.equal(marketingContent.en.features.items[0].title, "Understand your spending.");
  assert.equal(marketingContent.en.features.items[1].title, "Give every goal a place.");
  assert.match(marketingContent.en.faq.items[0][1], /Telegram or the web app/);
  assert.match(marketingContent.en.faq.items[1][1], /help you reach your goals/);
  assert.equal(
    marketingContent.en.security.points[2],
    "You can export your data or request its deletion"
  );
});

test("public beta calls to action describe receiving access credentials", () => {
  assert.equal(marketingContent.it.how.cta, "Ottieni l’accesso");
  assert.equal(marketingContent.it.pricing.cards[0][2], "Ottieni l’accesso");
  assert.equal(marketingContent.en.how.cta, "Get access");
  assert.equal(marketingContent.en.pricing.cards[0][2], "Get access");
});
