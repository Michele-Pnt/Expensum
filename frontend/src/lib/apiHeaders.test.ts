import assert from "node:assert/strict";
import test from "node:test";

import { invalidateCsrfToken } from "./csrf";
import { buildHeaders } from "./apiHeaders";

type TelegramGlobal = { Telegram?: { WebApp?: { initData?: string } } };
type MutableGlobal = typeof globalThis & {
  window?: Window & typeof globalThis & TelegramGlobal;
  fetch: typeof fetch;
};

const mutableGlobal = globalThis as MutableGlobal;
const realFetch = mutableGlobal.fetch;

/** Sostituisce l'endpoint CSRF e il contesto Telegram, senza toccare la rete. */
function setupEnvironment(initData?: string): void {
  invalidateCsrfToken();
  mutableGlobal.window = (initData === undefined
    ? {}
    : { Telegram: { WebApp: { initData } } }) as Window & typeof globalThis & TelegramGlobal;
  mutableGlobal.fetch = (async () =>
    new Response(JSON.stringify({ csrf_token: "token-123" }), {
      status: 200,
      headers: { "content-type": "application/json" },
    })) as typeof fetch;
}

function restoreEnvironment(): void {
  invalidateCsrfToken();
  Reflect.deleteProperty(mutableGlobal, "window");
  mutableGlobal.fetch = realFetch;
}

test("always sends the CSRF token", async (t) => {
  setupEnvironment();
  t.after(restoreEnvironment);

  const headers = (await buildHeaders()) as Record<string, string>;
  assert.equal(headers["X-CSRFToken"], "token-123");
  assert.equal("X-Telegram-Init-Data" in headers, false);
});

test("adds the Telegram init data only inside the mini app", async (t) => {
  setupEnvironment("query_id=AA&user=%7B%7D");
  t.after(restoreEnvironment);

  const headers = (await buildHeaders()) as Record<string, string>;
  assert.equal(headers["X-Telegram-Init-Data"], "query_id=AA&user=%7B%7D");
  assert.equal(headers["X-CSRFToken"], "token-123");
});

test("never sends an empty init data header", async (t) => {
  setupEnvironment("");
  t.after(restoreEnvironment);

  const headers = (await buildHeaders()) as Record<string, string>;
  assert.equal("X-Telegram-Init-Data" in headers, false);
});
