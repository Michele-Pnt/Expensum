export function getAtomStep(progress: number, stepCount: number): number {
  if (!Number.isInteger(stepCount) || stepCount <= 0) {
    throw new Error("stepCount must be a positive integer");
  }

  const normalized = Math.min(1, Math.max(0, progress));
  return Math.min(stepCount - 1, Math.floor(normalized * stepCount));
}
