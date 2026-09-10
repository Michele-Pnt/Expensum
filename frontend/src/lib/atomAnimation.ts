export const ATOM_IDLE_TIME_SCALE = 0.28;

export function getIdleAtomAnimationNames(names: string[]): string[] {
  return names.filter((name) => {
    const normalizedName = name.toLowerCase();
    return !normalizedName.includes("camera") && !normalizedName.includes("wobble");
  });
}
