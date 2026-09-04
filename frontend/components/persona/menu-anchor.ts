/**
 * Dropdown menus in the shell headers are anchored `right-0` to their
 * trigger. On phones the trigger can sit near the left edge, so a menu wider
 * than the space to its left renders off screen. Returns true when the menu
 * should be re-anchored to the trigger's left edge instead.
 */
export function shouldAnchorLeft(rect: { left: number }, margin = 8): boolean {
  return rect.left < margin;
}
