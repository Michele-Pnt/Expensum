// Token CSRF per le chiamate POST/PUT/DELETE autenticate via cookie di sessione browser.
// Le richieste che portano X-Telegram-Init-Data non ne hanno bisogno (vedi
// enforce_csrf_on_forms in src/dashboard/app.py), ma includerlo non causa danni
// quindi viene sempre allegato dove la pagina puo' aprirsi anche fuori dalla WebView.

let cachedToken: string | null = null;

export async function getCsrfToken(forceRefresh = false): Promise<string> {
  if (cachedToken && !forceRefresh) return cachedToken;
  const res = await fetch("/api/csrf-token", { credentials: "include" });
  const contentType = res.headers.get("content-type") ?? "";
  if (!res.ok || !contentType.includes("application/json")) {
    throw new Error("Impossibile ottenere il token di sicurezza della sessione");
  }
  const data = await res.json();
  if (typeof data.csrf_token !== "string" || !data.csrf_token) {
    throw new Error("Token di sicurezza della sessione non valido");
  }
  const token = data.csrf_token as string;
  cachedToken = token;
  return token;
}

export function invalidateCsrfToken(): void {
  cachedToken = null;
}
