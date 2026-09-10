export function getReferralCode(search: string): string | null {
  const value = new URLSearchParams(search).get("ref")?.trim();
  return value || null;
}
