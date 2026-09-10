export function isAtomNearViewport(
  sectionTop: number,
  viewportHeight: number,
  preloadMargin: number,
): boolean {
  return sectionTop <= viewportHeight + preloadMargin && sectionTop >= -viewportHeight - preloadMargin;
}
