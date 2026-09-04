/**
 * Back-navigation targets for the persona shells.
 *
 * The installed PWA has no browser chrome, so a deep-linked page (history
 * length 1) needs somewhere to go when the shell back button is pressed.
 * Both helpers are pure so they can be unit-tested in the node vitest
 * environment.
 */

function stripTrailingSlash(pathname: string): string {
  return pathname.length > 1 && pathname.endsWith("/") ? pathname.slice(0, -1) : pathname;
}

/**
 * Walk up `pathname` one segment at a time and return the first prefix that
 * appears in `known`; fall back to `home` when no prefix is known.
 *
 * `/coach/sessions/abc/skills` with known `/coach/sessions` → `/coach/sessions`.
 * `/coach/students/abc/passport` with no `/coach/students` → `home`.
 */
export function parentRoute(pathname: string, known: readonly string[], home: string): string {
  let current = stripTrailingSlash(pathname);
  while (current.includes("/")) {
    const cut = current.lastIndexOf("/");
    if (cut <= 0) break;
    current = current.slice(0, cut);
    if (known.includes(current)) return current;
  }
  return home;
}

/** True when `pathname` (trailing slash stripped) is exactly one of `known`. */
export function isTopLevel(pathname: string, known: readonly string[]): boolean {
  return known.includes(stripTrailingSlash(pathname));
}
