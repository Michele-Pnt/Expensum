export const GOAL_CODES = [
  "cashflow_control",
  "budget",
  "emergency_fund",
  "savings_goal",
  "increase_savings",
] as const;

export type OptionalConsentState = {
  product_analytics: boolean;
  marketing_email: boolean;
  algorithm_improvement: boolean;
  structured_text_usage: boolean;
  structured_voice_usage: boolean;
  ocr_text_usage: boolean;
};

export const DEFAULT_OPTIONAL_CONSENTS: OptionalConsentState = {
  product_analytics: true,
  marketing_email: true,
  algorithm_improvement: false,
  structured_text_usage: false,
  structured_voice_usage: false,
  ocr_text_usage: false,
};

export function acceptAllOptionalConsents(): OptionalConsentState {
  return {
    product_analytics: true,
    marketing_email: true,
    algorithm_improvement: true,
    structured_text_usage: true,
    structured_voice_usage: true,
    ocr_text_usage: true,
  };
}

export function toggleGoal(selected: string[], code: string): string[] {
  return selected.includes(code) ? selected.filter((item) => item !== code) : [...selected, code];
}

export function rejectAllOptionalConsents(): OptionalConsentState {
  return {
    product_analytics: false,
    marketing_email: false,
    algorithm_improvement: false,
    structured_text_usage: false,
    structured_voice_usage: false,
    ocr_text_usage: false,
  };
}
