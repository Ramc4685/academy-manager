/**
 * Query + ordering rules for the admin student pickers (add to roster, record
 * absence). L2 A0-2: the pickers used to load the first 50 students
 * alphabetically, so anyone later in the alphabet could not be picked once an
 * academy passed 50 records. They now search the server.
 */

import type { ListAdminStudentsParams } from "@/lib/api/admin";
import type { PersonLifecycle } from "@/lib/format/lifecycle-copy";

/** Lifecycles that still hold (or are coming back to) a seat. */
export const ON_THE_BOOKS: PersonLifecycle[] = [
  "active",
  "at_risk",
  "pending_cancel",
  "on_hold",
  "paused",
];

/** The server's page cap; past it the admin types to search. */
export const PICKER_LIMIT = 100;

/**
 * Every lifecycle, so a brand-new or returning child can be enrolled. Search
 * text goes to the server, which matches the whole academy, not one page.
 */
export function studentPickerParams(search: string): ListAdminStudentsParams {
  const query = search.trim();
  return query ? { search: query, limit: PICKER_LIMIT } : { limit: PICKER_LIMIT };
}

/** On-the-books students first, otherwise keeping the server's name order. */
export function orderPickerResults<T extends { lifecycle: PersonLifecycle }>(students: T[]): T[] {
  const rank = (s: T) => (ON_THE_BOOKS.includes(s.lifecycle) ? 0 : 1);
  return [...students].sort((a, b) => rank(a) - rank(b));
}
