import { getCsrfToken } from "@/lib/csrf";

/** Init data della mini-app Telegram, se la pagina è aperta nella WebView. */
export function getTelegramInitData(): string {
  if (typeof window === "undefined") return "";
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  return (window as any).Telegram?.WebApp?.initData ?? "";
}

/** Solo l'init data Telegram, senza il round-trip CSRF: per le chiamate GET,
 * esentate da `enforce_csrf_on_forms` (vedi src/dashboard/factory.py). */
export function buildReadHeaders(): HeadersInit {
  const init = getTelegramInitData();
  return init ? { "X-Telegram-Init-Data": init } : {};
}

/**
 * Header comuni a ogni chiamata autenticata del frontend: token CSRF e, dentro la
 * mini-app Telegram, l'init data che identifica la sessione.
 */
export async function buildHeaders(): Promise<HeadersInit> {
  const init = getTelegramInitData();
  const csrfToken = await getCsrfToken();
  const headers: Record<string, string> = { "X-CSRFToken": csrfToken };
  if (init) headers["X-Telegram-Init-Data"] = init;
  return headers;
}
