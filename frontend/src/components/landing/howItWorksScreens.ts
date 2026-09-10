export const HOW_SCREEN_TYPES = ["chat", "analysis", "dashboard", "report"] as const;

export type HowScreenType = (typeof HOW_SCREEN_TYPES)[number];

export function getHowScreenType(step: number): HowScreenType {
  return HOW_SCREEN_TYPES[step] ?? "chat";
}
