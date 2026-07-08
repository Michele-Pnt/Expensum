/**
 * Tracking eventi lato frontend — inoltrato server-side via /api/track.
 *
 * Il browser non carica mai script di PostHog/GA4/Meta né apre connessioni
 * verso i loro domini: la CSP resta chiusa a 'self'. Il backend Flask
 * (src/analytics.py) inoltra l'evento ai vendor abilitati in base al
 * consenso cookie corrente.
 *
 * Regole GDPR:
 * - distinct_id = chat_id Telegram (risolto server-side dalla sessione) o un
 *   id anonimo generato client-side, persistito in localStorage
 * - NON includere mai amount, category_name, merchant nelle properties
 * - NON includere mai contenuto di feedback o notifiche
 */
import { getCsrfToken } from "@/lib/csrf";

const ANONYMOUS_ID_KEY = "expensum_anonymous_id";

function getAnonymousId(): string {
  if (typeof window === "undefined") return "";
  let id = window.localStorage.getItem(ANONYMOUS_ID_KEY);
  if (!id) {
    id = crypto.randomUUID();
    window.localStorage.setItem(ANONYMOUS_ID_KEY, id);
  }
  return id;
}

function getConsent(): { analytics: boolean; marketing: boolean } {
  if (typeof window === "undefined") return { analytics: false, marketing: false };
  try {
    // vanilla-cookieconsent espone lo stato accettato via cookie dedicato;
    // fallback a "non concesso" se non ancora inizializzato (fail-closed).
    const w = window as unknown as {
      __cookieConsentApi?: { acceptedCategory: (c: string) => boolean };
    };
    if (!w.__cookieConsentApi) return { analytics: false, marketing: false };
    return {
      analytics: w.__cookieConsentApi.acceptedCategory("analytics"),
      marketing: w.__cookieConsentApi.acceptedCategory("marketing"),
    };
  } catch {
    return { analytics: false, marketing: false };
  }
}

async function sendEvent(event: string, properties?: Record<string, unknown>): Promise<void> {
  if (typeof window === "undefined") return;
  try {
    const csrfToken = await getCsrfToken();
    await fetch("/api/track", {
      method: "POST",
      credentials: "same-origin",
      headers: { "Content-Type": "application/json", "X-CSRFToken": csrfToken },
      body: JSON.stringify({
        event,
        properties: properties ?? {},
        anonymous_id: getAnonymousId(),
        consent: getConsent(),
      }),
    });
  } catch {
    // Fire-and-forget: il tracking non deve mai bloccare o rompere la UI.
  }
}

// ---------------------------------------------------------------------------
// Identificazione utente
// ---------------------------------------------------------------------------

export function identifyUser(distinctId: string, properties?: Record<string, string>) {
  void sendEvent("identify", { distinct_id: distinctId, ...properties });
}

// ---------------------------------------------------------------------------
// Pageview
// ---------------------------------------------------------------------------

// Segmenti dinamici che possono contenere token/id sensibili nell'URL: vanno
// oscurati prima di inviare il path a PostHog/GA4.
const SENSITIVE_PATH_PATTERNS: Array<[RegExp, string]> = [
  [/^\/reports\/[^/]+/, "/reports/[token]"],
];

function sanitizePath(path: string): string {
  for (const [pattern, replacement] of SENSITIVE_PATH_PATTERNS) {
    if (pattern.test(path)) return path.replace(pattern, replacement);
  }
  return path;
}

export function trackPageView(path: string) {
  void sendEvent("page_view", { path: sanitizePath(path) });
}

// ---------------------------------------------------------------------------
// Registrazione e onboarding
// ---------------------------------------------------------------------------

export function trackUserSignedUp(authMethod: "web" | "telegram") {
  void sendEvent("user_signed_up", { auth_method: authMethod });
}

export function trackOnboardingStepCompleted(stepName: string, stepNumber: number) {
  void sendEvent("onboarding_step_completed", { step_name: stepName, step_number: stepNumber });
}

export function trackOnboardingCompleted() {
  void sendEvent("onboarding_completed", { platform: "web" });
}

// ---------------------------------------------------------------------------
// Tracciamento spese
// ---------------------------------------------------------------------------

export type InputMethod = "text" | "voice" | "photo";

export function trackExpenseTracked(inputMethod: InputMethod) {
  void sendEvent("expense_tracked", { input_method: inputMethod });
}

export function trackExpenseTrackingFailed(reason: string, inputMethod: InputMethod = "text") {
  void sendEvent("expense_tracking_failed", { reason, input_method: inputMethod });
}

export function trackFirstExpenseTracked(inputMethod: InputMethod) {
  void sendEvent("first_expense_tracked", { input_method: inputMethod });
}

// ---------------------------------------------------------------------------
// Report
// ---------------------------------------------------------------------------

export function trackReportViewed(reportType: "weekly" | "monthly" | string) {
  void sendEvent("report_viewed", { report_type: reportType });
}

export function trackReportShared(reportType: "weekly" | "monthly" | string) {
  void sendEvent("report_shared", { report_type: reportType });
}

// ---------------------------------------------------------------------------
// Subscription e paywall
// ---------------------------------------------------------------------------

export function trackPaywallViewed(source?: string) {
  void sendEvent("paywall_viewed", { source: source ?? "direct" });
}

export function trackTrialStarted(planType: string) {
  void sendEvent("trial_started", { plan_type: planType });
}

export function trackSubscriptionStarted(planType: string, fromPlan?: string) {
  void sendEvent("subscription_started", { plan_type: planType, from_plan: fromPlan ?? "free" });
}

export function trackSubscriptionCancelled(planType: string) {
  void sendEvent("subscription_cancelled", { plan_type: planType });
}

export function trackSubscriptionPaused(planType: string) {
  void sendEvent("subscription_paused", { plan_type: planType });
}

// ---------------------------------------------------------------------------
// Feedback
// ---------------------------------------------------------------------------

export function trackFeedbackSubmitted() {
  void sendEvent("feedback_submitted");
}

// ---------------------------------------------------------------------------
// Stub futuri (sistemi non ancora implementati — G5/G6)
// ---------------------------------------------------------------------------

// TODO [G5]: habit_threshold_reached — emettere da backend Python quando il sistema streak è live
// TODO [G6]: referral_link_generated — emettere quando il sistema referral è live
// TODO [G6]: referral_signup — emettere da backend Python al completamento onboarding con referral
