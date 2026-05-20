"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import {
  listAdminUsers,
  updateAdminUserRole,
  type AdminUserRole,
  type AdminUserView,
} from "@/lib/api/admin";
import { queryKeys } from "@/lib/query/keys";
import { Avatar } from "@/components/ds/avatar";
import { Button } from "@/components/ds/button";
import { Card } from "@/components/ds/card";
import { Chip } from "@/components/ds/chip";
import { Overline } from "@/components/ds/typography";
import { ComingNextCard } from "./coming-next-card";

const ROLE_OPTIONS: AdminUserRole[] = ["admin", "coach", "parent"];

export function RolesPanel() {
  const queryClient = useQueryClient();
  const query = useQuery({ queryKey: queryKeys.admin.users(), queryFn: () => listAdminUsers() });
  const mutation = useMutation({
    mutationFn: ({ userId, role }: { userId: string; role: AdminUserRole }) =>
      updateAdminUserRole(userId, role),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: queryKeys.admin.users() });
    },
  });
  const users = query.data?.users ?? [];

  return (
    <section data-testid="admin-settings-roles" className="space-y-4">
      <Card p={24}>
        <div className="flex items-center justify-between gap-4">
          <Overline>Roles</Overline>
          {mutation.isError && (
            <p role="alert" className="text-sm font-medium text-red-700">
              {mutation.error.message}
            </p>
          )}
        </div>
        {query.isLoading ? (
          <div className="mt-5 space-y-2">
            {[0, 1, 2].map((i) => (
              <div key={i} className="h-14 animate-pulse rounded-md bg-rally-paper" />
            ))}
          </div>
        ) : users.length === 0 ? (
          <p className="mt-4 text-sm text-rally-subtle">No users found.</p>
        ) : (
          <div className="mt-5 overflow-x-auto">
            <table className="w-full min-w-[720px] text-sm">
              <thead>
                <tr className="border-b border-rally-line text-left">
                  <th className="px-2 pb-3 font-mono text-[10px] font-bold uppercase tracking-overline text-rally-muted">
                    User
                  </th>
                  <th className="px-2 pb-3 font-mono text-[10px] font-bold uppercase tracking-overline text-rally-muted">
                    Current role
                  </th>
                  <th className="px-2 pb-3 font-mono text-[10px] font-bold uppercase tracking-overline text-rally-muted">
                    Change role
                  </th>
                </tr>
              </thead>
              <tbody>
                {users.map((user) => (
                  <RoleRow
                    key={user.user_id}
                    user={user}
                    pending={mutation.isPending && mutation.variables?.userId === user.user_id}
                    onChange={(role) => mutation.mutate({ userId: user.user_id, role })}
                  />
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Card>
      <ComingNextCard
        title="Invites"
        description="No identity send-invite use case exists yet, so invite delivery stays deferred until that application workflow is added."
      />
    </section>
  );
}

function RoleRow({
  user,
  pending,
  onChange,
}: {
  user: AdminUserView;
  pending: boolean;
  onChange: (role: AdminUserRole) => void;
}) {
  return (
    <tr className="border-b border-rally-line last:border-0">
      <td className="px-2 py-3">
        <div className="flex items-center gap-3">
          <Avatar name={user.display_name || user.email} size={32} />
          <div>
            <div className="font-medium text-rally-ink">{user.display_name || user.email}</div>
            <div className="font-mono text-[10px] text-rally-muted">{user.email}</div>
          </div>
        </div>
      </td>
      <td className="px-2 py-3">
        <Chip variant={roleVariant(user.role)} label={user.role.toUpperCase()} />
      </td>
      <td className="px-2 py-3">
        <div className="flex flex-wrap gap-2">
          {ROLE_OPTIONS.map((role) => (
            <Button
              key={role}
              size="sm"
              variant={role === user.role ? "secondary" : "ghost"}
              disabled={pending || role === user.role}
              onClick={() => onChange(role)}
            >
              {role}
            </Button>
          ))}
        </div>
      </td>
    </tr>
  );
}

function roleVariant(role: AdminUserRole) {
  if (role === "admin") return "enrolled";
  if (role === "coach") return "autopayOn";
  return "manual";
}
