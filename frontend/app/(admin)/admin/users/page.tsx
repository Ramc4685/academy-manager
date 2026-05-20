"use client";

import { useState } from "react";
import { useQuery } from "@tanstack/react-query";

import {
  listAdminUsers,
  type AdminUserRole,
  type AdminUserView,
} from "@/lib/api/admin";
import { queryKeys } from "@/lib/query/keys";
import { Card } from "@/components/ds/card";
import { Chip } from "@/components/ds/chip";
import { Avatar } from "@/components/ds/avatar";

const roles: Array<{ label: string; value: AdminUserRole | undefined }> = [
  { label: "All", value: undefined },
  { label: "Coaches", value: "coach" },
  { label: "Parents", value: "parent" },
  { label: "Admins", value: "admin" },
];

export default function AdminUsersPage() {
  const [role, setRole] = useState<AdminUserRole | undefined>();
  const { data, isLoading, isError } = useQuery({
    queryKey: queryKeys.admin.users(role),
    queryFn: () => listAdminUsers(role),
  });

  return (
    <section data-testid="admin-users" className="space-y-6">
      <div className="flex gap-2">
        {roles.map((r) => (
          <button
            key={r.label}
            type="button"
            onClick={() => setRole(r.value)}
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

      {isError ? (
        <p role="alert" className="rounded-md bg-red-50 p-3 text-sm text-red-700">
          Could not load users.
        </p>
      ) : isLoading ? (
        <Skeleton />
      ) : (data?.users.length ?? 0) === 0 ? (
        <p className="text-sm text-rally-subtle" data-testid="admin-users-empty">
          No users found.
        </p>
      ) : (
        <Card p={20}>
          <UsersTable users={data!.users} />
        </Card>
      )}
    </section>
  );
}

function mapRoleToStatus(role: string): any {
  if (role === "admin") return "enrolled";
  if (role === "coach") return "autopayOn";
  return "manual";
}

function UsersTable({ users }: { users: AdminUserView[] }) {
  return (
    <div className="overflow-x-auto">
      <table className="w-full text-sm">
        <thead>
          <tr className="border-b border-neutral-200 text-left dark:border-neutral-800">
            <th className="px-2 pb-3 font-mono text-[10px] font-bold uppercase tracking-overline text-rally-muted">Name</th>
            <th className="px-2 pb-3 font-mono text-[10px] font-bold uppercase tracking-overline text-rally-muted">Email</th>
            <th className="px-2 pb-3 font-mono text-[10px] font-bold uppercase tracking-overline text-rally-muted">Role</th>
            <th className="px-2 pb-3 font-mono text-[10px] font-bold uppercase tracking-overline text-rally-muted">Status</th>
            <th className="px-2 pb-3 font-mono text-[10px] font-bold uppercase tracking-overline text-rally-muted">Mongo ID</th>
          </tr>
        </thead>
        <tbody>
          {users.map((user) => (
            <tr key={user.user_id} data-testid={`admin-users-row-${user.user_id}`} className="border-b border-neutral-100 last:border-0 dark:border-neutral-800">
              <td className="px-2 py-3">
                <div className="flex items-center gap-3">
                  <Avatar name={user.display_name} size={32} />
                  <div className="font-medium text-rally-base">{user.display_name}</div>
                </div>
              </td>
              <td className="px-2 py-3 text-rally-base">{user.email}</td>
              <td className="px-2 py-3">
                <Chip variant={mapRoleToStatus(user.role)} label={user.role.toUpperCase()} />
              </td>
              <td className="px-2 py-3">
                <Chip variant={user.status === "active" ? "enrolled" : "expired"} label={user.status.toUpperCase()} />
              </td>
              <td className="px-2 py-3 font-mono text-[10px] text-rally-subtle">{user.user_id}</td>
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
