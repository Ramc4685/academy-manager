"use client";

import { useState } from "react";
import { useQuery } from "@tanstack/react-query";

import {
  listAdminUsers,
  type AdminUserRole,
  type AdminUserView,
} from "@/lib/api/admin";
import { queryKeys } from "@/lib/query/keys";

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
    <section data-testid="admin-users">
      <div className="mb-6 flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="text-2xl font-semibold">Coaches & parents</h1>
          <p className="mt-1 text-sm text-neutral-500">
            Firebase signs them in; Mongo controls their app role.
          </p>
        </div>
        <div className="flex overflow-hidden rounded-md border border-neutral-200 dark:border-neutral-800">
          {roles.map((r) => (
            <button
              key={r.label}
              type="button"
              onClick={() => setRole(r.value)}
              className={`min-h-touch px-3 text-sm font-medium ${
                role === r.value
                  ? "bg-blue-600 text-white"
                  : "bg-white text-neutral-700 hover:bg-neutral-50 dark:bg-neutral-900 dark:text-neutral-300"
              }`}
            >
              {r.label}
            </button>
          ))}
        </div>
      </div>

      {isError ? (
        <p role="alert" className="rounded-md bg-red-50 p-3 text-sm text-red-700">
          Could not load users.
        </p>
      ) : isLoading ? (
        <Skeleton />
      ) : (data?.users.length ?? 0) === 0 ? (
        <p className="text-sm text-neutral-500">No users found.</p>
      ) : (
        <UsersTable users={data!.users} />
      )}
    </section>
  );
}

function UsersTable({ users }: { users: AdminUserView[] }) {
  return (
    <div className="overflow-x-auto rounded-lg border border-neutral-200 bg-white dark:border-neutral-800 dark:bg-neutral-900">
      <table className="w-full text-sm">
        <thead>
          <tr className="border-b border-neutral-200 text-left text-neutral-500 dark:border-neutral-800">
            <th className="px-4 py-3 font-medium">Name</th>
            <th className="px-4 py-3 font-medium">Email</th>
            <th className="px-4 py-3 font-medium">Role</th>
            <th className="px-4 py-3 font-medium">Status</th>
            <th className="px-4 py-3 font-medium">Mongo ID</th>
          </tr>
        </thead>
        <tbody>
          {users.map((user) => (
            <tr key={user.user_id} className="border-b border-neutral-100 last:border-0 dark:border-neutral-800">
              <td className="px-4 py-3 font-medium">{user.display_name}</td>
              <td className="px-4 py-3 text-neutral-600 dark:text-neutral-400">{user.email}</td>
              <td className="px-4 py-3 capitalize">{user.role}</td>
              <td className="px-4 py-3">
                <span className="rounded-full bg-emerald-50 px-2 py-0.5 text-xs font-medium text-emerald-700 dark:bg-emerald-950 dark:text-emerald-300">
                  {user.status}
                </span>
              </td>
              <td className="px-4 py-3 font-mono text-xs text-neutral-500">{user.user_id}</td>
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
