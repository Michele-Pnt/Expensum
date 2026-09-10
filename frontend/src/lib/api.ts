import { buildHeaders, buildReadHeaders } from "@/lib/apiHeaders";
import { invalidateCsrfToken } from "@/lib/csrf";

const API_BASE = process.env.NEXT_PUBLIC_API_URL ?? "";

/** Errore di una chiamata API: `status` e `body` (JSON già parsato, se possibile)
 * permettono ai chiamanti di distinguere i casi (401, 404, validazione...) senza
 * riparsare `message`. Per un 401 `message` è sempre `"auth_401"`, lo stesso
 * sentinel già usato in tutta l'app per instradare al login. */
export class ApiError extends Error {
  status: number;
  body: unknown;

  constructor(status: number, body: unknown, message?: string) {
    super(message ?? `Errore API ${status}`);
    this.name = "ApiError";
    this.status = status;
    this.body = body;
  }
}

/**
 * Messaggio utente per un errore di `apiFetch`: usa `error` dal body JSON del
 * backend quando c'è (validazione, conflitto...), altrimenti `fallback` — sia
 * per un errore di rete puro (nessuna risposta) sia per un body senza `error`.
 */
export function apiErrorMessage(error: unknown, fallback: string): string {
  if (error instanceof ApiError && error.body && typeof error.body === "object" && "error" in error.body) {
    const message = (error.body as { error?: unknown }).error;
    if (typeof message === "string" && message) return message;
  }
  return fallback;
}

export interface ApiFetchOptions {
  method?: "GET" | "POST" | "PUT" | "DELETE" | "PATCH";
  /** Serializzato come JSON. Se assente, la richiesta non ha body. */
  body?: unknown;
  /** Aggiunta come query string (solo utile con GET). */
  params?: Record<string, string>;
  /** Riprova una volta con un token CSRF fresco su 400/403. Default: true per
   * i metodi non-GET (le GET non passano da CSRF lato Flask), false per GET. */
  csrfRetry?: boolean;
  signal?: AbortSignal;
}

/**
 * Client fetch unico per l'intera app: unifica i vecchi `fetchApi` (solo
 * lettura, duplicato identico in calendario/analytics) e `fetchWithCsrfRetry`
 * (scrittura, duplicato identico in goals/mutuo).
 *
 * - GET: nessun body, `params` diventa query string; header di sola lettura
 *   (`buildReadHeaders`, solo init-data Telegram) — niente round-trip CSRF,
 *   Flask non protegge le GET (vedi `enforce_csrf_on_forms` in
 *   `src/dashboard/factory.py`).
 * - POST/PUT/DELETE/PATCH: `Content-Type: application/json` + token CSRF
 *   (`buildHeaders`); su 400/403 invalida il token e ritenta una sola volta.
 * - 401 su qualunque metodo: `ApiError` con `message === "auth_401"` — il
 *   chiamante decide se reindirizzare al login (comportamento invariato).
 * - Risposta senza body (es. alcune DELETE): ritorna `undefined` invece di far
 *   esplodere il parsing JSON.
 * - Risposta 2xx con body non-JSON (es. pagina interstiziale ngrok): `ApiError`
 *   invece di lasciar propagare il `SyntaxError` grezzo di `JSON.parse`.
 */
export async function apiFetch<T = unknown>(path: string, options: ApiFetchOptions = {}): Promise<T> {
  const { method = "GET", body, params, signal } = options;
  const isGet = method === "GET";
  const csrfRetry = options.csrfRetry ?? !isGet;

  const query = params ? `?${new URLSearchParams(params).toString()}` : "";
  const url = `${API_BASE}${path}${query}`;

  const doFetch = async (): Promise<Response> => {
    const headers: Record<string, string> = isGet
      ? { ...(buildReadHeaders() as Record<string, string>) }
      : { ...((await buildHeaders()) as Record<string, string>) };
    const init: RequestInit = { method, signal, headers };
    if (body !== undefined) {
      headers["Content-Type"] = "application/json";
      init.body = JSON.stringify(body);
    }
    return fetch(url, init);
  };

  let res = await doFetch();
  if (csrfRetry && (res.status === 400 || res.status === 403)) {
    invalidateCsrfToken();
    res = await doFetch();
  }

  if (res.status === 401) {
    throw new ApiError(401, null, "auth_401");
  }
  if (!res.ok) {
    const errorBody = await res.json().catch(() => null);
    throw new ApiError(res.status, errorBody, errorBody?.error);
  }

  const text = await res.text();
  if (!text) return undefined as T;
  try {
    return JSON.parse(text) as T;
  } catch {
    throw new ApiError(res.status, null, "Risposta non valida dal server");
  }
}
