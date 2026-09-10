import assert from "node:assert/strict";
import test from "node:test";

import { invalidateCsrfToken } from "./csrf";
import { apiFetch, apiErrorMessage, ApiError } from "./api";

type MutableGlobal = typeof globalThis & {
  window?: Window & typeof globalThis;
  fetch: typeof fetch;
};

const mutableGlobal = globalThis as MutableGlobal;
const realFetch = mutableGlobal.fetch;

function jsonResponse(status: number, body: unknown): Response {
  return new Response(body === undefined ? "" : JSON.stringify(body), {
    status,
    headers: body === undefined ? {} : { "content-type": "application/json" },
  });
}

function restoreEnvironment(): void {
  invalidateCsrfToken();
  Reflect.deleteProperty(mutableGlobal, "window");
  mutableGlobal.fetch = realFetch;
}

test("GET does not fetch a CSRF token", async (t) => {
  t.after(restoreEnvironment);
  let csrfRequested = false;
  mutableGlobal.fetch = (async (input: RequestInfo | URL) => {
    if (String(input).includes("/api/csrf-token")) {
      csrfRequested = true;
      return jsonResponse(200, { csrf_token: "token-123" });
    }
    return jsonResponse(200, { ok: true });
  }) as typeof fetch;

  const data = await apiFetch<{ ok: boolean }>("/api/whatever");
  assert.equal(data.ok, true);
  assert.equal(csrfRequested, false);
});

test("GET forwards params as query string", async (t) => {
  t.after(restoreEnvironment);
  let requestedUrl = "";
  mutableGlobal.fetch = (async (input: RequestInfo | URL) => {
    requestedUrl = String(input);
    return jsonResponse(200, { ok: true });
  }) as typeof fetch;

  await apiFetch("/api/calendar/month", { params: { year: "2026", month: "9" } });
  assert.match(requestedUrl, /\/api\/calendar\/month\?year=2026&month=9/);
});

test("non-GET sends the CSRF token and retries once on 400", async (t) => {
  t.after(restoreEnvironment);
  let call = 0;
  mutableGlobal.fetch = (async (input: RequestInfo | URL) => {
    if (String(input).includes("/api/csrf-token")) {
      return jsonResponse(200, { csrf_token: `token-${call}` });
    }
    call += 1;
    if (call === 1) return jsonResponse(400, { error: "csrf scaduto" });
    return jsonResponse(201, { id: 42 });
  }) as typeof fetch;

  const data = await apiFetch<{ id: number }>("/api/savings-goals", {
    method: "POST",
    body: { name: "Vacanza" },
  });
  assert.equal(data.id, 42);
  assert.equal(call, 2);
});

test("throws ApiError with message 'auth_401' on 401", async (t) => {
  t.after(restoreEnvironment);
  mutableGlobal.fetch = (async () => jsonResponse(401, { error: "nope" })) as typeof fetch;

  await assert.rejects(
    () => apiFetch("/api/settings"),
    (err: unknown) => {
      assert.ok(err instanceof ApiError);
      assert.equal(err.message, "auth_401");
      assert.equal(err.status, 401);
      return true;
    },
  );
});

test("throws ApiError carrying the backend error body on other failures", async (t) => {
  t.after(restoreEnvironment);
  mutableGlobal.fetch = (async () => jsonResponse(404, { error: "Non trovato" })) as typeof fetch;

  await assert.rejects(
    () => apiFetch("/api/reports/abc"),
    (err: unknown) => {
      assert.ok(err instanceof ApiError);
      assert.equal(err.status, 404);
      assert.deepEqual(err.body, { error: "Non trovato" });
      assert.equal(err.message, "Non trovato");
      return true;
    },
  );
});

test("apiErrorMessage prefers the backend error, then falls back", () => {
  assert.equal(apiErrorMessage(new ApiError(409, { error: "Nome già esistente" }), "fallback"), "Nome già esistente");
  assert.equal(apiErrorMessage(new ApiError(500, {}), "fallback"), "fallback");
  assert.equal(apiErrorMessage(new Error("network down"), "fallback"), "fallback");
});

test("throws a handled ApiError instead of a raw JSON parse error on non-JSON 2xx bodies", async (t) => {
  t.after(restoreEnvironment);
  mutableGlobal.fetch = (async () =>
    new Response("<html>ngrok interstitial</html>", {
      status: 200,
      headers: { "content-type": "text/html" },
    })) as typeof fetch;

  await assert.rejects(
    () => apiFetch("/api/mortgage-simulations/evaluate"),
    (err: unknown) => {
      assert.ok(err instanceof ApiError);
      assert.ok(!(err instanceof SyntaxError));
      assert.equal(err.status, 200);
      return true;
    },
  );
});

test("returns undefined for an empty response body", async (t) => {
  t.after(restoreEnvironment);
  mutableGlobal.fetch = (async (input: RequestInfo | URL) => {
    if (String(input).includes("/api/csrf-token")) {
      return jsonResponse(200, { csrf_token: "token-123" });
    }
    return jsonResponse(200, undefined);
  }) as typeof fetch;

  const data = await apiFetch("/api/space/accounts/1", { method: "DELETE" });
  assert.equal(data, undefined);
});
