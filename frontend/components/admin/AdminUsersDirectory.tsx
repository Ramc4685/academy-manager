"use client";

import { useState } from "react";
import type { ReactNode } from "react";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import * as Dialog from "@radix-ui/react-dialog";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Plus } from "lucide-react";

import {
  createAdminUser,
  listAdminUsers,
  type AdminUserRole,
  type AdminUserView,
} from "@/lib/api/admin";
import { queryKeys } from "@/lib/query/keys";
import { Card } from "@/components/ds/card";
import { Chip } from "@/components/ds/chip";
import { roleToChipVariant } from "@/lib/admin/role-chip";
import { Avatar } from "@/components/ds/avatar";
import { Button } from "@/components/ds/button";
import { CoachEngagementStatsStrip } from "@/components/admin/CoachEngagementStatsStrip";

const roles: Array<{ label: string; value: AdminUserRole | undefined }> = [
  { label: "All", value: undefined },
  { label: "Coaches", value: "coach" },
  { label: "Parents", value: "parent" },
  { label: "Admins", value: "admin" },
];

function parseRoleParam(value: string | null): AdminUserRole | undefined {
  return value === "coach" || value === "parent" || value === "admin"
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
  const [createOpen, setCreateOpen] = useState(false);

  // URL is the single source of truth for the active role tab.
  const role = fixedRole ?? parseRoleParam(searchParams.get("role"));

  function selectRole(next: AdminUserRole | undefined) {
    const params = new URLSearchParams(searchParams.toString());
    if (next) params.set("role", next);
    else params.delete("role");
    const query = params.toString();
    router.replace(query ? `?${query}` : "?", { scroll: false });
  }

  const { data, isLoading, isError } = useQuery({
    queryKey: queryKeys.admin.users(role),
    queryFn: () => listAdminUsers(role),
  });

  const users = data?.users ?? [];
  const createLabel = fixedRole === "coach" ? "Add coach" : fixedRole === "parent" ? "Add parent" : "Add user";

  return (
    <section data-testid="admin-users" className="space-y-6">
      <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
        {!fixedRole ? (
          <div className="flex gap-2">
            {roles.map((r) => (
              <button
                key={r.label}
                type="button"
                onClick={() => selectRole(r.value)}
                className={`rounded-full px-3 py-1.5 text-xs font-medium transition-colors ${
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

      {!fixedRole && role === "coach" && <CoachEngagementStatsStrip />}

      <CreateUserDialog
        open={createOpen}
        onOpenChange={setCreateOpen}
        fixedRole={fixedRole}
        onCreated={() => {
          setCreateOpen(false);
          void queryClient.invalidateQueries({ queryKey: ["admin", "users"] });
        }}
      />

      {isError ? (
        <p role="alert" className="rounded-md bg-red-50 p-3 text-sm text-red-700">
          Could not load users.
        </p>
      ) : isLoading ? (
        <Skeleton />
      ) : users.length === 0 ? (
        <p className="text-sm text-rally-subtle" data-testid="admin-users-empty">
          No users found.
        </p>
      ) : (
        <Card p={20}>
          <UsersTable users={users} />
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
  const [role, setRole] = useState<Extract<AdminUserRole, "coach" | "parent">>(
    fixedRole ?? "parent",
  );
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
                  value={role}
                  onChange={(event) => setRole(event.target.value as Extract<AdminUserRole, "coach" | "parent">)}
                  className="h-10 w-full rounded-md border border-neutral-200 bg-white px-3 text-sm text-rally-base outline-none focus:border-rally-cobalt-600 focus:ring-2 focus:ring-rally-cobalt-600/15"
                >
                  <option value="parent">Parent</option>
                  <option value="coach">Coach</option>
                </select>
              </Field>
            )}
            <Field label="Name" htmlFor="create-user-name">
              <input
                id="create-user-name"
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
              <td className="px-2 py-3 text-rally-base">{user.email}</td>
              <td className="px-2 py-3 text-rally-muted">{user.phone || "-"}</td>
              <td className="px-2 py-3">
                <Chip variant={roleToChipVariant(user.role)} label={user.role.toUpperCase()} />
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
