import { strict as assert } from "node:assert";
import { readFileSync } from "node:fs";
import { test } from "node:test";

const italian = readFileSync(new URL("./PrivacyContentIt.tsx", import.meta.url), "utf8");
const english = readFileSync(new URL("./PrivacyContentEn.tsx", import.meta.url), "utf8");

test("privacy notices describe self-service registration and new data flows", () => {
  for (const expected of ["verifica", "recupero", "profilo", "algoritmi", "90 giorni", "Brevo"]) {
    assert.match(italian, new RegExp(expected, "i"));
  }
  assert.doesNotMatch(italian, /Tally.*creazione.*account/i);
});

test("English notice mentions the same new processing concepts", () => {
  for (const expected of ["verification", "password", "profile", "algorithm", "90", "Brevo"]) {
    assert.match(english, new RegExp(expected, "i"));
  }
});
