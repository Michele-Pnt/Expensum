/**
 * Typed helpers per il tracking PostHog lato frontend.
 *
 * Regole GDPR:
 * - distinct_id = chat_id Telegram (pseudonimo) o web user_id
 * - NON includere mai amount, category_name, merchant nelle properties
 * - NON includere mai contenuto di feedback o notifiche
 */
import posthog from "posthog-js";

// ---------------------------------------------------------------------------
// Identificazione utente
// ---------------------------------------------------------------------------

export function identifyUser(distinctId: string, properties?: Record<string, string>) {
  posthog.identify(distinctId, properties);
}

// ---------------------------------------------------------------------------
// Registrazione e onboarding
// ---------------------------------------------------------------------------

export function trackUserSignedUp(authMethod: "web" | "telegram") {
  posthog.capture("user_signed_up", { auth_method: authMethod });
}

export function trackOnboardingStepCompleted(stepName: string, stepNumber: number) {
  posthog.capture("onboarding_step_completed", { step_name: stepName, step_number: stepNumber });
}

export function trackOnboardingCompleted() {
  posthog.capture("onboarding_completed", { platform: "web" });
}

// ---------------------------------------------------------------------------
// Tracciamento spese
// ---------------------------------------------------------------------------

export type InputMethod = "text" | "voice" | "photo";

export function trackExpenseTracked(inputMethod: InputMethod) {
  posthog.capture("expense_tracked", { input_method: inputMethod });
}

export function trackExpenseTrackingFailed(reason: string, inputMethod: InputMethod = "text") {
  posthog.capture("expense_tracking_failed", { reason, input_method: inputMethod });
}

export function trackFirstExpenseTracked(inputMethod: InputMethod) {
  posthog.capture("first_expense_tracked", { input_method: inputMethod });
}

// ---------------------------------------------------------------------------
// Report
// ---------------------------------------------------------------------------

export function trackReportViewed(reportType: "weekly" | "monthly" | string) {
  posthog.capture("report_viewed", { report_type: reportType });
}

export function trackReportShared(reportType: "weekly" | "monthly" | string) {
  posthog.capture("report_shared", { report_type: reportType });
}

// ---------------------------------------------------------------------------
// Subscription e paywall
// ---------------------------------------------------------------------------

export function trackPaywallViewed(source?: string) {
  posthog.capture("paywall_viewed", { source: source ?? "direct" });
}

export function trackTrialStarted(planType: string) {
  posthog.capture("trial_started", { plan_type: planType });
}

export function trackSubscriptionStarted(planType: string, fromPlan?: string) {
  posthog.capture("subscription_started", { plan_type: planType, from_plan: fromPlan ?? "free" });
}

export function trackSubscriptionCancelled(planType: string) {
  posthog.capture("subscription_cancelled", { plan_type: planType });
}

export function trackSubscriptionPaused(planType: string) {
  posthog.capture("subscription_paused", { plan_type: planType });
}

// ---------------------------------------------------------------------------
// Feedback
// ---------------------------------------------------------------------------

export function trackFeedbackSubmitted() {
  posthog.capture("feedback_submitted");
}

// ---------------------------------------------------------------------------
// Stub futuri (sistemi non ancora implementati — G5/G6)
// ---------------------------------------------------------------------------

// TODO [G5]: habit_threshold_reached — emettere da backend Python quando il sistema streak è live
// TODO [G6]: referral_link_generated — emettere quando il sistema referral è live
// TODO [G6]: referral_signup — emettere da backend Python al completamento onboarding con referral
