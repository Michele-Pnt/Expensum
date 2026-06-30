// Token CSRF per le chiamate POST/PUT/DELETE autenticate via cookie di sessione browser.
// Le richieste che portano X-Telegram-Init-Data non ne hanno bisogno (vedi
// enforce_csrf_on_forms in src/dashboard/app.py), ma includerlo non causa danni
// quindi viene sempre allegato dove la pagina puo' aprirsi anche fuori dalla WebView.

let cachedToken: string | null = null;

export async function getCsrfToken(): Promise<string> {
  if (cachedToken) return cachedToken;
  const res = await fetch("/api/csrf-token", { credentials: "same-origin" });
  const data = await res.json();
  cachedToken = data.csrf_token;
  return cachedToken as string;
}
