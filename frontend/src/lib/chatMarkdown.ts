/**
 * Markdown minimale usato nelle bubble di chat e nel composer globale.
 *
 * Il testo può contenere contenuto originato dall'utente (nome del movimento,
 * trascrizione vocale, reply del server che riecheggia l'input) e viene reso con
 * `dangerouslySetInnerHTML`: l'escape dell'HTML va fatto SEMPRE prima di
 * applicare le regex, altrimenti la history persistita diventa uno stored XSS.
 */

const HTML_ENTITIES: Record<string, string> = {
  "&": "&amp;",
  "<": "&lt;",
  ">": "&gt;",
  '"': "&quot;",
  "'": "&#39;",
};

export function escapeHtml(text: string): string {
  return text.replace(/[&<>"']/g, (char) => HTML_ENTITIES[char]);
}

/** Grassetto, corsivo, codice inline e a capo — su testo già reso inerte. */
export function renderChatMarkdown(text: string): string {
  return escapeHtml(text)
    .replace(/\*\*(.+?)\*\*/g, "<strong>$1</strong>")
    .replace(/_(.+?)_/g, "<em>$1</em>")
    .replace(/`(.+?)`/g, "<code>$1</code>")
    .replace(/\n/g, "<br/>");
}
