"use client";

import { useEffect, useMemo, useState } from "react";
import type { ReactNode } from "react";
import Link from "next/link";
import type { Route } from "next";
import { useRouter, useSearchParams } from "next/navigation";
import * as Dialog from "@radix-ui/react-dialog";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Plus, Search, Users } from "lucide-react";

import {
  createAdminUser,
  listAdminUsers,
  type AdminUserRole,
  type AdminUserView,
} from "@/lib/api/admin";
import { assignableRoles } from "@/lib/auth/assignable-roles";
import { filterUsersBySearch } from "@/lib/admin/user-search";
import { useIsOwner } from "@/components/admin/owner-context";
import { queryKeys } from "@/lib/query/keys";
import { Card } from "@/components/ds/card";
import { Chip } from "@/components/ds/chip";
import { roleToChipVariant } from "@/lib/admin/role-chip";
import { roleLabel } from "@/lib/admin/role-label";
import { Avatar } from "@/components/ds/avatar";
import { Button } from "@/components/ds/button";
import { ErrorNotice } from "@/components/ds/error-notice";
import { ContactLinks } from "@/components/ds/contact-links";
import { PhoneList, PhoneListRow } from "@/components/ds/phone-row";
import { useIsPhone } from "@/lib/use-is-phone";
import { CoachEngagementStatsStrip } from "@/components/admin/CoachEngagementStatsStrip";
import { BulkInviteDialog } from "@/components/admin/bulk-invite-dialog";

const roles: Array<{ label: string; value: AdminUserRole | undefined }> = [
  { label: "All", value: undefined },
  { label: "Coaches", value: "coach" },
  { label: "Assistant coaches", value: "assistant_coach" },
  { label: "Parents", value: "parent" },
  { label: "Admins", value: "admin" },
];

/** How long a keystroke waits before it narrows the table. */
const SEARCH_DEBOUNCE_MS = 150;

function parseRoleParam(value: string | null): AdminUserRole | undefined {
  return value === "coach" ||
    value === "assistant_coach" ||
    value === "parent" ||
    value === "admin"
    ? value
    : undefined;
}

export function AdminUsersDirectory({
  fixedRole,
}: {
  fixedRole?: Extract<AdminUserRole, "coach" | "parent">;
}) {
  const queryClient = useQueryClient();
  const router = useRouter();
  const searchParams = useSearchParams();
  // #839: `/admin/users/new` was a second add-user form. It now forwards here
  // with `?add=1`, so there is one form and the old bookmark still works.
  const [createOpen, setCreateOpen] = useState(() => searchParams.get("add") === "1");
  const [bulkOpen, setBulkOpen] = useState(false);
  const [searchInput, setSearchInput] = useState("");
  const [search, setSearch] = useState("");

  useEffect(() => {
    const timer = setTimeout(() => setSearch(searchInput), SEARCH_DEBOUNCE_MS);
    return () => clearTimeout(timer);
  }, [searchInput]);

  // URL is the single source of truth for the active role tab.
  const role = fixedRole ?? parseRoleParam(searchParams.get("role"));

  function setCreateDialogOpen(open: boolean) {
    setCreateOpen(open);
    if (!open && searchParams.get("add")) {
      const params = new URLSearchParams(searchParams.toString());
      params.delete("add");
      const query = params.toString();
      router.replace(query ? `?${query}` : "?", { scroll: false });
    }
  }

  function selectRole(next: AdminUserRole | undefined) {
    const params = new URLSearchParams(searchParams.toString());
    if (next) params.set("role", next);
    else params.delete("role");
    const query = params.toString();
    router.replace(query ? `?${query}` : "?", { scroll: false });
  }

  const { data, isLoading, isError, isFetching, refetch } = useQuery({
    queryKey: queryKeys.admin.users(role),
    queryFn: () => listAdminUsers(role),
  });

  const allUsers = useMemo(() => data?.users ?? [], [data]);
  // `listAdminUsers` takes only a role, so the search narrows what is loaded.
  const users = useMemo(() => filterUsersBySearch(allUsers, search), [allUsers, search]);
  const createLabel = fixedRole === "coach" ? "Add coach" : fixedRole === "parent" ? "Add parent" : "Add user";
  // The bulk endpoint mints parents only (role is hardcoded server-side), so
  // the action is offered on the parent tab and on the unfiltered directory.
  const canBulkInvite = (fixedRole ?? role ?? "parent") === "parent";

  return (
    <section data-testid="admin-users" className="space-y-6">
      <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
        {!fixedRole ? (
          <div className="flex flex-wrap gap-2">
            {roles.map((r) => (
              <button
                key={r.label}
                type="button"
                onClick={() => selectRole(r.value)}
                // #847: 44px on a phone, unchanged on desktop.
                className={`inline-flex min-h-touch items-center rounded-full px-3 py-1.5 text-xs font-medium transition-colors md:min-h-0 ${
                  role === r.value
                    ? "bg-neutral-900 text-white dark:bg-white dark:text-neutral-900"
                    : "bg-neutral-100 text-neutral-600 hover:bg-neutral-200 dark:bg-neutral-800 dark:text-neutral-400 dark:hover:bg-neutral-700"
                }`}
              >
                {r.label}
              </button>
            ))}
          </div>
        ) : (
          <div />
        )}
        {/* #839: role tabs were the only way to narrow the directory, so
            finding one person meant scrolling. Same control as Students. */}
        <div className="relative min-w-0 sm:w-[280px]">
          <label htmlFor="admin-users-search" className="sr-only">
            Search users
          </label>
          <Search
            aria-hidden="true"
            className="pointer-events-none absolute left-3 top-1/2 size-4 -translate-y-1/2 text-rally-muted"
          />
          <input
            id="admin-users-search"
            value={searchInput}
            onChange={(event) => setSearchInput(event.target.value)}
            placeholder="Search name, email or phone"
            className="h-10 w-full rounded-md border border-neutral-200 bg-white pl-9 pr-3 font-body text-sm text-rally-base outline-none transition placeholder:text-rally-subtle focus:border-rally-cobalt-600 focus:ring-2 focus:ring-rally-cobalt-600/15"
          />
        </div>
        <div className="flex flex-wrap gap-2">
          {canBulkInvite && (
            <Button
              type="button"
              size="sm"
              variant="secondary"
              icon={<Users className="size-4" aria-hidden="true" />}
              onClick={() => setBulkOpen(true)}
              data-testid="admin-users-bulk-invite"
            >
              Bulk invite parents
            </Button>
          )}
          <Button
            type="button"
            size="sm"
            icon={<Plus className="size-4" aria-hidden="true" />}
            onClick={() => setCreateOpen(true)}
            data-testid="admin-users-add"
          >
            {createLabel}
          </Button>
        </div>
      </div>

      {!fixedRole && role === "coach" && <CoachEngagementStatsStrip />}

      <CreateUserDialog
        open={createOpen}
        onOpenChange={setCreateDialogOpen}
        fixedRole={fixedRole}
        onCreated={() => {
          setCreateDialogOpen(false);
          void queryClient.invalidateQueries({ queryKey: ["admin", "users"] });
        }}
      />

      <BulkInviteDialog
        open={bulkOpen}
        onOpenChange={setBulkOpen}
        onInvited={() => {
          void queryClient.invalidateQueries({ queryKey: ["admin", "users"] });
        }}
      />

      {isError ? (
        // #837: a dead end. The directory now offers the request again.
        <ErrorNotice
          testId="admin-users-error"
          message="Could not load users."
          onRetry={() => void refetch()}
          retrying={isFetching}
        />
      ) : isLoading ? (
        <Skeleton />
      ) : users.length === 0 ? (
        <p className="text-sm text-rally-subtle" data-testid="admin-users-empty">
          {search ? `No users match “${search}”.` : "No users found."}
        </p>
      ) : (
        <Card p={0}>
          <UsersList users={users} />
        </Card>
      )}
    </section>
  );
}

function CreateUserDialog({
  open,
  onOpenChange,
  fixedRole,
  onCreated,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  fixedRole?: Extract<AdminUserRole, "coach" | "parent">;
  onCreated: () => void;
}) {
  // #839: this dialog is now the only add-user form, so it offers exactly the
  // roles the current user may grant — the standalone page's rule, which the
  // BFF enforces anyway (`ensure_can_assign_role`).
  const roleOptions = assignableRoles(useIsOwner());
  const [role, setRole] = useState<AdminUserRole>(fixedRole ?? "parent");
  const [displayName, setDisplayName] = useState("");
  const [email, setEmail] = useState("");
  const [phone, setPhone] = useState("");
  const [reason, setReason] = useState("Manual user onboarding");
  const [error, setError] = useState<string | null>(null);

  const mutation = useMutation({
    mutationFn: () =>
      createAdminUser({
        role: fixedRole ?? role,
        display_name: displayName.trim(),
        email: email.trim().toLowerCase(),
        phone: phone.trim() || null,
        reason,
      }),
    onSuccess: () => {
      setDisplayName("");
      setEmail("");
      setPhone("");
      setReason("Manual user onboarding");
      setError(null);
      onCreated();
    },
    onError: (err: unknown) => {
      setError(err instanceof Error ? err.message : "Could not create user.");
    },
  });

  return (
    <Dialog.Root open={open} onOpenChange={onOpenChange}>
      <Dialog.Portal>
        <Dialog.Overlay className="fixed inset-0 z-40 bg-neutral-950/40" />
        <Dialog.Content className="fixed left-1/2 top-1/2 z-50 w-[min(92vw,520px)] -translate-x-1/2 -translate-y-1/2 rounded-lg border border-rally-line bg-white p-5 shadow-xl focus:outline-none">
          <Dialog.Title className="font-display text-xl font-bold text-rally-ink">
            {fixedRole === "coach" ? "Add coach" : fixedRole === "parent" ? "Add parent" : "Add user"}
          </Dialog.Title>
          {(fixedRole ?? role) === "parent" && (
            // Carried over from the retired /admin/users/new page (#839): this
            // is the one fact about adding a parent that is not obvious.
            <Dialog.Description className="mt-2 text-sm text-rally-muted">
              Parents get a “set your password” email automatically, so they can
              log in with any email address — no Google account needed.
            </Dialog.Description>
          )}
          <form
            className="mt-4 space-y-4"
            onSubmit={(event) => {
              event.preventDefault();
              setError(null);
              mutation.mutate();
            }}
          >
            {!fixedRole && (
              <Field label="Role" htmlFor="create-user-role">
                <select
                  id="create-user-role"
                  data-testid="new-user-role"
                  value={role}
                  onChange={(event) => setRole(event.target.value as AdminUserRole)}
                  className="h-10 w-full rounded-md border border-neutral-200 bg-white px-3 text-sm text-rally-base outline-none focus:border-rally-cobalt-600 focus:ring-2 focus:ring-rally-cobalt-600/15"
                >
                  {roleOptions.map((option) => (
                    <option key={option} value={option}>
                      {roleLabel(option)}
                    </option>
                  ))}
                </select>
              </Field>
            )}
            <Field label="Name" htmlFor="create-user-name">
              <input
                id="create-user-name"
                data-testid="new-user-name"
                value={displayName}
                onChange={(event) => setDisplayName(event.target.value)}
                className="h-10 w-full rounded-md border border-neutral-200 bg-white px-3 text-sm text-rally-base outline-none focus:border-rally-cobalt-600 focus:ring-2 focus:ring-rally-cobalt-600/15"
                required
                maxLength={120}
              />
            </Field>
            <Field label="Email" htmlFor="create-user-email">
              <input
                id="create-user-email"
                data-testid="new-user-email"
                type="email"
                value={email}
                onChange={(event) => setEmail(event.target.value)}
                className="h-10 w-full rounded-md border border-neutral-200 bg-white px-3 text-sm text-rally-base outline-none focus:border-rally-cobalt-600 focus:ring-2 focus:ring-rally-cobalt-600/15"
                required
                maxLength={254}
              />
            </Field>
            <Field label="Phone" htmlFor="create-user-phone">
              <input
                id="create-user-phone"
                value={phone}
                onChange={(event) => setPhone(event.target.value)}
                className="h-10 w-full rounded-md border border-neutral-200 bg-white px-3 text-sm text-rally-base outline-none focus:border-rally-cobalt-600 focus:ring-2 focus:ring-rally-cobalt-600/15"
                maxLength={40}
              />
            </Field>
            <Field label="Reason" htmlFor="create-user-reason">
              <input
                id="create-user-reason"
                value={reason}
                onChange={(event) => setReason(event.target.value)}
                className="h-10 w-full rounded-md border border-neutral-200 bg-white px-3 text-sm text-rally-base outline-none focus:border-rally-cobalt-600 focus:ring-2 focus:ring-rally-cobalt-600/15"
                required
                maxLength={500}
              />
            </Field>
            {error && (
              <p role="alert" className="rounded-md bg-red-50 p-3 text-sm text-red-700">
                {error}
              </p>
            )}
            <div className="flex justify-end gap-2 pt-2">
              <Button type="button" variant="secondary" onClick={() => onOpenChange(false)}>
                Cancel
              </Button>
              <Button type="submit" disabled={mutation.isPending}>
                {mutation.isPending ? "Saving..." : "Save"}
              </Button>
            </div>
          </form>
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  );
}

function Field({
  label,
  htmlFor,
  children,
}: {
  label: string;
  htmlFor: string;
  children: ReactNode;
}) {
  return (
    <label className="block" htmlFor={htmlFor}>
      <span className="mb-1.5 block font-mono text-[10px] font-bold uppercase tracking-overline text-rally-muted">
        {label}
      </span>
      {children}
    </label>
  );
}

/**
 * #847: one list, two layouts, exactly one mounted — see
 * `lib/use-is-phone.ts`. The phone rows keep the table's `data-testid`s.
 *
 * #857: the actions trigger is `admin-users-actions-<id>`, deliberately NOT
 * the row testid with `actions-` appended — an id that starts with the row's
 * own `admin-users-row-` prefix is matched by every prefix selector that means
 * to pick rows.
 */
function UsersList({ users }: { users: AdminUserView[] }) {
  const isPhone = useIsPhone();
  if (isPhone) {
    return (
      <PhoneList aria-label="Users" data-testid="admin-users-phone-list">
        {users.map((user) => {
          const href = `/admin/users/${encodeURIComponent(user.user_id)}` as Route;
          return (
            <PhoneListRow
              key={user.user_id}
              data-testid={`admin-users-row-${user.user_id}`}
              leading={<Avatar name={user.display_name} size={32} />}
              title={user.display_name}
              href={href}
              titleTestId={`admin-users-link-${user.user_id}`}
              primary={
                <Chip
                  variant={user.status === "active" ? "enrolled" : "expired"}
                  label={user.status.toUpperCase()}
                />
              }
              actionsLabel={`Actions for ${user.display_name}`}
              actionsTestId={`admin-users-actions-${user.user_id}`}
              actions={[{ key: "open", label: "Open user", href }]}
              contact={{ phone: user.phone, email: user.email }}
              secondary={
                <>
                  <div>
                    <Chip
                      variant={roleToChipVariant(user.role)}
                      label={roleLabel(user.role).toUpperCase()}
                    />
                  </div>
                  {/* #865: the same ContactLinks the desktop cell uses, so the
                      two layouts cannot disagree about what is tappable. */}
                  <ContactLinks
                    name={user.display_name}
                    email={user.email}
                    phone={user.phone}
                    fallback="No phone on file"
                  />
                </>
              }
            />
          );
        })}
      </PhoneList>
    );
  }
  return (
    <div className="p-5">
      <UsersTable users={users} />
    </div>
  );
}

function UsersTable({ users }: { users: AdminUserView[] }) {
  return (
    <div className="overflow-x-auto">
      <table className="w-full text-sm">
        <thead>
          <tr className="border-b border-neutral-200 text-left dark:border-neutral-800">
            <th className="px-2 pb-3 font-mono text-[10px] font-bold uppercase tracking-overline text-rally-muted">Name</th>
            <th className="px-2 pb-3 font-mono text-[10px] font-bold uppercase tracking-overline text-rally-muted">Email</th>
            <th className="px-2 pb-3 font-mono text-[10px] font-bold uppercase tracking-overline text-rally-muted">Phone</th>
            <th className="px-2 pb-3 font-mono text-[10px] font-bold uppercase tracking-overline text-rally-muted">Role</th>
            <th className="px-2 pb-3 font-mono text-[10px] font-bold uppercase tracking-overline text-rally-muted">Status</th>
          </tr>
        </thead>
        <tbody>
          {users.map((user) => (
            <tr key={user.user_id} data-testid={`admin-users-row-${user.user_id}`} className="border-b border-neutral-100 last:border-0 dark:border-neutral-800">
              <td className="px-2 py-3">
                <Link
                  href={`/admin/users/${encodeURIComponent(user.user_id)}`}
                  className="group flex items-center gap-3 rounded focus:outline-none focus:ring-2 focus:ring-rally-cobalt-600"
                  data-testid={`admin-users-link-${user.user_id}`}
                >
                  <Avatar name={user.display_name} size={32} />
                  <div className="font-medium text-rally-base group-hover:underline">
                    {user.display_name}
                  </div>
                </Link>
              </td>
              {/* #865: both cells were plain text, so reaching a coach or a
                  parent from the directory meant copying the number out. */}
              <td className="px-2 py-3 text-rally-base">
                <ContactLinks name={user.display_name} email={user.email} />
              </td>
              <td className="px-2 py-3 text-rally-muted">
                <ContactLinks name={user.display_name} phone={user.phone} fallback="-" />
              </td>
              <td className="px-2 py-3">
                <Chip variant={roleToChipVariant(user.role)} label={roleLabel(user.role).toUpperCase()} />
              </td>
              <td className="px-2 py-3">
                <Chip variant={user.status === "active" ? "enrolled" : "expired"} label={user.status.toUpperCase()} />
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function Skeleton() {
  return (
    <div className="space-y-2">
      {[0, 1, 2].map((i) => (
        <div key={i} className="h-14 animate-pulse rounded-lg bg-neutral-100 dark:bg-neutral-800" />
      ))}
    </div>
  );
}
