"use client";

import { useEffect, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import {
  addAdminUserRole,
  getAdminUser,
  listAdminUsers,
  removeAdminUserRole,
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
  const [editingUserId, setEditingUserId] = useState<string | null>(null);
  const users = query.data?.users ?? [];

  return (
    <section data-testid="admin-settings-roles" className="space-y-4">
      <Card p={24}>
        <Overline>Roles</Overline>
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
                    Roles
                  </th>
                </tr>
              </thead>
              <tbody>
                {users.map((user) => (
                  <RoleRow
                    key={user.user_id}
                    user={user}
                    editing={editingUserId === user.user_id}
                    onToggleEdit={() =>
                      setEditingUserId((current) =>
                        current === user.user_id ? null : user.user_id,
                      )
                    }
                    onSaved={() => {
                      setEditingUserId(null);
                      void queryClient.invalidateQueries({ queryKey: queryKeys.admin.users() });
                      void queryClient.invalidateQueries({ queryKey: queryKeys.admin.userDetail(user.user_id) });
                    }}
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
  editing,
  onToggleEdit,
  onSaved,
}: {
  user: AdminUserView;
  editing: boolean;
  onToggleEdit: () => void;
  onSaved: () => void;
}) {
  return (
    <>
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
          <Button size="sm" variant="ghost" onClick={onToggleEdit}>
            {editing ? "Cancel" : "Edit roles"}
          </Button>
        </td>
      </tr>
      {editing && (
        <tr className="border-b border-rally-line last:border-0">
          <td colSpan={3} className="bg-rally-paper px-2 py-4">
            <RoleEditor user={user} onSaved={onSaved} />
          </td>
        </tr>
      )}
    </>
  );
}

function RoleEditor({ user, onSaved }: { user: AdminUserView; onSaved: () => void }) {
  const detailQuery = useQuery({
    queryKey: queryKeys.admin.userDetail(user.user_id),
    queryFn: () => getAdminUser(user.user_id),
  });
  const currentRoles = detailQuery.data?.roles?.length ? detailQuery.data.roles : [user.role];

  const [selected, setSelected] = useState<AdminUserRole[]>(currentRoles);
  const [reason, setReason] = useState("Admin role change");
  const [submitError, setSubmitError] = useState<string | null>(null);

  useEffect(() => {
    if (detailQuery.data) {
      setSelected(detailQuery.data.roles.length > 0 ? detailQuery.data.roles : [user.role]);
    }
  }, [detailQuery.data, user.role]);

  const mutation = useMutation({
    mutationFn: async () => {
      const current = new Set(currentRoles);
      const next = new Set(selected);
      for (const role of ROLE_OPTIONS) {
        if (next.has(role) && !current.has(role)) {
          await addAdminUserRole(user.user_id, role, reason);
        }
      }
      for (const role of ROLE_OPTIONS) {
        if (current.has(role) && !next.has(role)) {
          await removeAdminUserRole(user.user_id, role, reason);
        }
      }
    },
    onSuccess: () => {
      setSubmitError(null);
      onSaved();
    },
    onError: (err: unknown) => {
      setSubmitError(err instanceof Error ? err.message : "Could not update roles.");
    },
  });

  const toggle = (role: AdminUserRole) => {
    setSelected((prev) => (prev.includes(role) ? prev.filter((r) => r !== role) : [...prev, role]));
  };

  if (detailQuery.isLoading) {
    return <div className="h-10 animate-pulse rounded-md bg-neutral-100" />;
  }

  return (
    <form
      className="space-y-3"
      data-testid={`admin-settings-role-form-${user.user_id}`}
      onSubmit={(event) => {
        event.preventDefault();
        setSubmitError(null);
        if (selected.length === 0) {
          setSubmitError("User must keep at least one role.");
          return;
        }
        mutation.mutate();
      }}
    >
      <p className="text-xs text-rally-muted">
        A user can hold multiple roles — e.g. an admin who also coaches, or a coach who is also a
        parent.
      </p>
      <div className="flex flex-wrap gap-3">
        {ROLE_OPTIONS.map((role) => (
          <label key={role} className="inline-flex items-center gap-2 text-sm">
            <input
              type="checkbox"
              checked={selected.includes(role)}
              onChange={() => toggle(role)}
              data-testid={`admin-settings-role-checkbox-${user.user_id}-${role}`}
            />
            <span className="capitalize">{role}</span>
          </label>
        ))}
      </div>
      <div className="flex items-center gap-2">
        <input
          value={reason}
          onChange={(event) => setReason(event.target.value)}
          className="h-9 w-64 rounded-md border border-neutral-200 bg-white px-3 text-sm text-rally-base outline-none focus:border-rally-cobalt-600 focus:ring-2 focus:ring-rally-cobalt-600/15"
          required
          maxLength={500}
          aria-label="Reason"
        />
        <Button type="submit" size="sm" variant="primary" disabled={mutation.isPending}>
          {mutation.isPending ? "Saving..." : "Save roles"}
        </Button>
      </div>
      {submitError && (
        <p role="alert" className="text-sm font-medium text-red-700">
          {submitError}
        </p>
      )}
    </form>
  );
}

function roleVariant(role: AdminUserRole) {
  if (role === "admin") return "enrolled";
  if (role === "coach") return "autopayOn";
  return "manual";
}
