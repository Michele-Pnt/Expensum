export type OptionalConsentState = {
  product_analytics: boolean;
  marketing_email: boolean;
  algorithm_improvement: boolean;
  structured_text_usage: boolean;
  structured_voice_usage: boolean;
  ocr_text_usage: boolean;
};

export function mergeConsentState(
  local: OptionalConsentState,
  server: Partial<OptionalConsentState>,
): OptionalConsentState {
  return { ...local, ...server };
}
