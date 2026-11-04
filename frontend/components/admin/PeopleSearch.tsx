"use client";

/**
 * Issue #865: one people search for the whole admin shell.
 *
 * Students, Families and Users each had their own search box on their own
 * page. An admin holding a name — a parent on the phone, a child at the desk
 * — had to guess which of the three lists that person lived in before they
 * could start looking, and guessed wrong for every parent who was also a
 * coach.
 *
 * Deliberately NOT a route. A `/admin/search` page would mean a manifest
 * entry, a back-stack entry and a lost place in whatever the admin was doing;
 * this opens over the current page and closes again. It also adds no polling:
 * nothing is fetched until the dialog is open AND the query is long enough,
 * and every read is one the list pages already make —
 * `listAdminStudents({ search })`, `fetchBillingSetup({ q })` and
 * `listAdminUsers()` with the client filter from #839. The grouping rules
 * live in `lib/admin/people-search.ts`, where they are unit-tested.
 */

import { useEffect, useState } from "react";
import Link from "next/link";
import type { Route } from "next";
import { useQuery } from "@tanstack/react-query";
import { Search } from "lucide-react";

import { fetchBillingSetup, listAdminStudents, listAdminUsers } from "@/lib/api/admin";
import {
  PEOPLE_SEARCH_LIMIT,
  PEOPLE_SEARCH_MIN_CHARS,
  peopleSearchGroups,
} from "@/lib/admin/people-search";
import { queryKeys } from "@/lib/query/keys";

import { Modal } from "@/components/ds/modal";

export function PeopleSearch() {
  const [open, setOpen] = useState(false);
  const [input, setInput] = useState("");
  const [query, setQuery] = useState("");

  // Same 300ms the Families page and the Users directory already use, so the
  // three reads behind one keystroke stay one burst.
  useEffect(() => {
    const timer = window.setTimeout(() => setQuery(input.trim()), 300);
    return () => window.clearTimeout(timer);
  }, [input]);

  const ready = query.length >= PEOPLE_SEARCH_MIN_CHARS;

  const studentsQuery = useQuery({
    queryKey: queryKeys.admin.students({ search: query, limit: PEOPLE_SEARCH_LIMIT }),
    queryFn: () => listAdminStudents({ search: query, limit: PEOPLE_SEARCH_LIMIT }),
    enabled: open && ready,
  });
  const familiesQuery = useQuery({
    queryKey: queryKeys.admin.peopleSearchFamilies(query),
    queryFn: () => fetchBillingSetup({ q: query, limit: PEOPLE_SEARCH_LIMIT }),
    enabled: open && ready,
  });
  // `listAdminUsers` takes no query — this is the whole directory, cached
  // under the key the Users page uses, filtered on the client.
  const usersQuery = useQuery({
    queryKey: queryKeys.admin.users(),
    queryFn: () => listAdminUsers(),
    enabled: open && ready,
  });

  const groups = peopleSearchGroups({
    query,
    students: studentsQuery.data?.students,
    families: familiesQuery.data?.rows,
    users: usersQuery.data?.users,
  });

  const loading =
    ready && (studentsQuery.isPending || familiesQuery.isPending || usersQuery.isPending);
  const failed = studentsQuery.isError && familiesQuery.isError && usersQuery.isError;

  const close = () => {
    setOpen(false);
    setInput("");
    setQuery("");
  };

  return (
    <>
      <button
        type="button"
        aria-label="Search people"
        data-testid="admin-people-search-open"
        onClick={() => setOpen(true)}
        className="min-h-touch min-w-touch flex items-center justify-center rounded-md text-rally-muted hover:bg-rally-paper focus:outline-none focus:ring-2 focus:ring-rally-cobalt-600"
      >
        <Search className="size-5" aria-hidden="true" />
      </button>

      <Modal open={open} onClose={close} title="Search people" size="md">
        <div data-testid="admin-people-search">
          <label htmlFor="admin-people-search-input" className="sr-only">
            Search students, families and staff
          </label>
          <input
            id="admin-people-search-input"
            data-testid="admin-people-search-input"
            value={input}
            autoComplete="off"
            onChange={(event) => setInput(event.target.value)}
            placeholder="Name, email or phone"
            className="h-11 w-full rounded-md border border-rally-line bg-white px-3 font-body text-sm text-rally-base outline-none placeholder:text-rally-subtle focus:border-rally-cobalt-600 focus:ring-2 focus:ring-rally-cobalt-600/15"
          />

          <div className="mt-3 max-h-[60vh] overflow-y-auto">
            {!ready ? (
              <p className="px-1 py-6 text-center text-sm text-rally-muted">
                Type at least {PEOPLE_SEARCH_MIN_CHARS} letters of a name.
              </p>
            ) : failed ? (
              <p
                data-testid="admin-people-search-error"
                className="px-1 py-6 text-center text-sm text-status-red-800"
              >
                Could not search right now. Nobody was found, which is not the same as
                nobody matching.
              </p>
            ) : loading ? (
              <p className="px-1 py-6 text-center text-sm text-rally-muted">Searching…</p>
            ) : groups.length === 0 ? (
              <p
                data-testid="admin-people-search-empty"
                className="px-1 py-6 text-center text-sm text-rally-muted"
              >
                No students, families or staff match “{query}”.
              </p>
            ) : (
              groups.map((group) => (
                <section key={group.id} className="py-1">
                  <h3
                    data-testid={`admin-people-search-group-${group.id}`}
                    className="px-1 pb-1 font-mono text-[10px] font-bold uppercase tracking-overline text-rally-muted"
                  >
                    {group.label}
                  </h3>
                  <ul role="list" className="divide-y divide-rally-line">
                    {group.hits.map((hit) => (
                      <li key={`${group.id}-${hit.key}`}>
                        <Link
                          href={hit.href as Route}
                          data-testid={`admin-people-search-hit-${group.id}-${hit.key}`}
                          onClick={close}
                          className="flex min-h-touch flex-col justify-center rounded px-1 py-2 hover:bg-rally-paper focus:outline-none focus:ring-2 focus:ring-rally-cobalt-600"
                        >
                          <span className="text-sm font-semibold text-rally-base">
                            {hit.name}
                          </span>
                          {hit.detail && (
                            <span className="break-words text-[13px] text-rally-muted">
                              {hit.detail}
                            </span>
                          )}
                        </Link>
                      </li>
                    ))}
                  </ul>
                </section>
              ))
            )}
          </div>
        </div>
      </Modal>
    </>
  );
}
