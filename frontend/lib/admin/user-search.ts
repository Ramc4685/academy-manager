import type { AdminUserView } from "@/lib/api/admin";

/**
 * Issue #839: the Users directory had role tabs but no search, so finding one
 * parent among hundreds meant scrolling. `listAdminUsers` takes only a `role`
 * param, so the filter runs over the rows already on the client — the same
 * fields the table prints, so what matches is what the admin can see.
 */
export function matchesUserSearch(user: AdminUserView, query: string): boolean {
  const needle = query.trim().toLowerCase();
  if (!needle) return true;
  return [user.display_name, user.email, user.phone].some(
    (field) => typeof field === "string" && field.toLowerCase().includes(needle),
  );
}

/** The matching rows, in their original order. */
export function filterUsersBySearch(
  users: readonly AdminUserView[],
  query: string,
): AdminUserView[] {
  const needle = query.trim();
  if (!needle) return [...users];
  return users.filter((user) => matchesUserSearch(user, needle));
}
