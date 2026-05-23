"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { useParams } from "next/navigation";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ArrowLeft, RefreshCw } from "lucide-react";

import {
  getAdminUser,
  updateAdminUser,
  updateAdminUserRole,
  type AdminUserDetail,
  type AdminUserRole,
} from "@/lib/api/admin";
import { queryKeys } from "@/lib/query/keys";
import { Avatar } from "@/components/ds/avatar";
import { Button } from "@/components/ds/button";
import { Card } from "@/components/ds/card";
import { Chip } from "@/components/ds/chip";
import { Overline } from "@/components/ds/typography";

const editableStatuses = ["active", "inactive", "disabled"] as const;
const academyRoles: AdminUserRole[] = ["admin", "coach", "parent"];

export default function AdminUserDetailPage() {
  const params = useParams<{ userId: string }>();
  const userId = params?.userId ?? "";
  const queryClient = useQueryClient();

  const userQuery = useQuery({
    queryKey: queryKeys.admin.userDetail(userId),
    queryFn: () => getAdminUser(userId),
    enabled: Boolean(userId),
    retry: false,
  });

  if (!userId) {
    return <StateCard message="Missing user." />;
  }

  if (userQuery.isPending) {
    return (
      <section className="space-y-4">
        <BackLink />
        <Card p={20}>
          <div
            className="h-24 animate-pulse rounded-lg bg-neutral-100 dark:bg-neutral-800"
            aria-label="Loading user"
          />
        </Card>
      </section>
    );
  }

  if (userQuery.isError) {
    return <StateCard message="Could not load user." isError />;
  }

  const user = userQuery.data;
  return (
    <section className="space-y-6" data-testid="admin-user-detail">
      <BackLink />
      <Header user={user} />
      <div className="grid gap-6 lg:grid-cols-3">
        <Card p={20} className="lg:col-span-2">
          <Overline>Profile</Overline>
          <UserEditForm
            user={user}
            onSaved={() => {
              void queryClient.invalidateQueries({ queryKey: queryKeys.admin.userDetail(userId) });
              void queryClient.invalidateQueries({ queryKey: queryKeys.admin.users() });
            }}
          />
        </Card>
        <Card p={20}>
          <Overline>Access</Overline>
          <RoleChangePanel
            user={user}
            onSaved={() => {
              void queryClient.invalidateQueries({ queryKey: queryKeys.admin.userDetail(userId) });
              void queryClient.invalidateQueries({ queryKey: queryKeys.admin.users() });
            }}
          />
        </Card>
      </div>
    </section>
  );
}

function StateCard({ message, isError = false }: { message: string; isError?: boolean }) {
  return (
    <section className="space-y-4">
      <BackLink />
      <Card p={20}>
        <p role={isError ? "alert" : undefined} className="text-sm text-rally-muted">
          {message}
        </p>
      </Card>
    </section>
  );
}

function BackLink() {
  return (
    <Link
      href="/admin/users"
      className="inline-flex items-center gap-1.5 rounded text-sm text-rally-muted hover:text-rally-ink focus:outline-none focus:ring-2 focus:ring-rally-cobalt-600"
    >
      <ArrowLeft className="size-4" aria-hidden="true" />
      <span>All users</span>
    </Link>
  );
}

function Header({ user }: { user: AdminUserDetail }) {
  return (
    <Card p={20}>
      <div className="flex flex-col gap-4 sm:flex-row sm:items-center sm:justify-between">
        <div className="flex min-w-0 items-center gap-4">
          <Avatar name={user.display_name} size={56} />
          <div className="min-w-0">
            <h2 className="truncate font-display text-xl font-semibold text-rally-ink">
              {user.display_name}
            </h2>
            <div className="mt-1 flex items-center gap-2">
              <Chip variant={roleVariant(user.role)} label={user.role.toUpperCase()} />
              <Chip
                variant={user.status === "active" ? "enrolled" : "expired"}
                label={user.status.toUpperCase()}
              />
            </div>
          </div>
        </div>
        <div className="text-sm text-rally-muted">
          <a
            href={`mailto:${user.email}`}
            className="block hover:underline focus:outline-none focus:ring-2 focus:ring-rally-cobalt-600 rounded"
          >
            {user.email}
          </a>
          {user.phone && (
            <a
              href={`tel:${user.phone}`}
              className="block hover:underline focus:outline-none focus:ring-2 focus:ring-rally-cobalt-600 rounded"
            >
              {user.phone}
            </a>
          )}
        </div>
      </div>
    </Card>
  );
}

function UserEditForm({ user, onSaved }: { user: AdminUserDetail; onSaved: () => void }) {
  const [displayName, setDisplayName] = useState(user.display_name);
  const [phone, setPhone] = useState(user.phone ?? "");
  const [status, setStatus] = useState(user.status);
  const [reason, setReason] = useState("Admin user update");
  const [submitError, setSubmitError] = useState<string | null>(null);
  const [submitOk, setSubmitOk] = useState(false);

  useEffect(() => {
    setDisplayName(user.display_name);
    setPhone(user.phone ?? "");
    setStatus(user.status);
  }, [user.display_name, user.phone, user.status]);

  const mutation = useMutation({
    mutationFn: () =>
      updateAdminUser(user.user_id, {
        display_name: displayName !== user.display_name ? displayName : undefined,
        phone: phone !== (user.phone ?? "") ? phone || null : undefined,
        status: status !== user.status ? status : undefined,
        reason,
      }),
    onSuccess: () => {
      setSubmitError(null);
      setSubmitOk(true);
      onSaved();
    },
    onError: (err: unknown) => {
      setSubmitOk(false);
      setSubmitError(err instanceof Error ? err.message : "Could not save user.");
    },
  });

  const dirty =
    displayName !== user.display_name || phone !== (user.phone ?? "") || status !== user.status;

  return (
    <form
      className="mt-3 space-y-4"
      data-testid="admin-user-edit-form"
      onSubmit={(event) => {
        event.preventDefault();
        setSubmitOk(false);
        setSubmitError(null);
        mutation.mutate();
      }}
    >
      <Field label="Display name" htmlFor="user-display-name">
        <input
          id="user-display-name"
          value={displayName}
          onChange={(event) => setDisplayName(event.target.value)}
          className="h-10 w-full rounded-md border border-neutral-200 bg-white px-3 text-sm text-rally-base outline-none focus:border-rally-cobalt-600 focus:ring-2 focus:ring-rally-cobalt-600/15"
          required
          maxLength={120}
        />
      </Field>

      <Field label="Phone" htmlFor="user-phone">
        <input
          id="user-phone"
          value={phone}
          onChange={(event) => setPhone(event.target.value)}
          className="h-10 w-full rounded-md border border-neutral-200 bg-white px-3 text-sm text-rally-base outline-none focus:border-rally-cobalt-600 focus:ring-2 focus:ring-rally-cobalt-600/15"
          maxLength={40}
        />
      </Field>

      <Field label="Status" htmlFor="user-status">
        <select
          id="user-status"
          value={status}
          onChange={(event) => setStatus(event.target.value)}
          className="h-10 w-full rounded-md border border-neutral-200 bg-white px-3 text-sm text-rally-base outline-none focus:border-rally-cobalt-600 focus:ring-2 focus:ring-rally-cobalt-600/15"
        >
          {editableStatuses.map((value) => (
            <option key={value} value={value}>
              {value[0].toUpperCase()}
              {value.slice(1)}
            </option>
          ))}
        </select>
      </Field>

      <Field label="Reason" htmlFor="user-edit-reason">
        <input
          id="user-edit-reason"
          value={reason}
          onChange={(event) => setReason(event.target.value)}
          className="h-10 w-full rounded-md border border-neutral-200 bg-white px-3 text-sm text-rally-base outline-none focus:border-rally-cobalt-600 focus:ring-2 focus:ring-rally-cobalt-600/15"
          required
          maxLength={500}
        />
      </Field>

      <MutationMessages error={submitError} ok={submitOk} />

      <div className="flex items-center gap-2">
        <Button
          type="submit"
          variant="primary"
          size="sm"
          disabled={!dirty || mutation.isPending}
          icon={mutation.isPending ? <RefreshCw className="size-3.5 animate-spin" /> : undefined}
        >
          {mutation.isPending ? "Saving..." : "Save changes"}
        </Button>
        {dirty && (
          <Button
            type="button"
            variant="secondary"
            size="sm"
            onClick={() => {
              setDisplayName(user.display_name);
              setPhone(user.phone ?? "");
              setStatus(user.status);
              setSubmitError(null);
              setSubmitOk(false);
            }}
          >
            Reset
          </Button>
        )}
      </div>
    </form>
  );
}

function RoleChangePanel({ user, onSaved }: { user: AdminUserDetail; onSaved: () => void }) {
  const [role, setRole] = useState<AdminUserRole>(user.role);
  const [reason, setReason] = useState("Admin role change");
  const [submitError, setSubmitError] = useState<string | null>(null);
  const [submitOk, setSubmitOk] = useState(false);

  useEffect(() => {
    setRole(user.role);
  }, [user.role]);

  const mutation = useMutation({
    mutationFn: () => updateAdminUserRole(user.user_id, role, reason),
    onSuccess: () => {
      setSubmitError(null);
      setSubmitOk(true);
      onSaved();
    },
    onError: (err: unknown) => {
      setSubmitOk(false);
      setSubmitError(err instanceof Error ? err.message : "Could not change role.");
    },
  });

  return (
    <form
      className="mt-3 space-y-4"
      data-testid="admin-user-role-form"
      onSubmit={(event) => {
        event.preventDefault();
        setSubmitOk(false);
        setSubmitError(null);
        mutation.mutate();
      }}
    >
      <DetailList
        rows={[
          { label: "Linked students", value: String(user.linked_student_count) },
          { label: "Current role", value: user.role.toUpperCase() },
        ]}
      />

      <Field label="Academy role" htmlFor="user-role">
        <select
          id="user-role"
          value={role}
          onChange={(event) => setRole(event.target.value as AdminUserRole)}
          className="h-10 w-full rounded-md border border-neutral-200 bg-white px-3 text-sm text-rally-base outline-none focus:border-rally-cobalt-600 focus:ring-2 focus:ring-rally-cobalt-600/15"
        >
          {academyRoles.map((value) => (
            <option key={value} value={value}>
              {value[0].toUpperCase()}
              {value.slice(1)}
            </option>
          ))}
        </select>
      </Field>

      <Field label="Role change reason" htmlFor="user-role-reason">
        <input
          id="user-role-reason"
          value={reason}
          onChange={(event) => setReason(event.target.value)}
          className="h-10 w-full rounded-md border border-neutral-200 bg-white px-3 text-sm text-rally-base outline-none focus:border-rally-cobalt-600 focus:ring-2 focus:ring-rally-cobalt-600/15"
          required
          maxLength={500}
        />
      </Field>

      <MutationMessages error={submitError} ok={submitOk} />

      <Button
        type="submit"
        variant="primary"
        size="sm"
        disabled={role === user.role || mutation.isPending}
        icon={mutation.isPending ? <RefreshCw className="size-3.5 animate-spin" /> : undefined}
      >
        {mutation.isPending ? "Saving..." : "Change role"}
      </Button>
    </form>
  );
}

function DetailList({ rows }: { rows: Array<{ label: string; value: string }> }) {
  return (
    <dl className="grid grid-cols-1 gap-3 text-sm">
      {rows.map((row) => (
        <div key={row.label} className="flex items-center justify-between">
          <dt className="text-rally-muted">{row.label}</dt>
          <dd className="font-mono text-rally-ink tabular-nums">{row.value}</dd>
        </div>
      ))}
    </dl>
  );
}

function MutationMessages({ error, ok }: { error: string | null; ok: boolean }) {
  return (
    <>
      {error && (
        <p role="alert" className="rounded-md border border-red-200 bg-red-50 p-2 text-sm text-red-700">
          {error}
        </p>
      )}
      {ok && (
        <p role="status" className="rounded-md border border-emerald-200 bg-emerald-50 p-2 text-sm text-emerald-800">
          Saved.
        </p>
      )}
    </>
  );
}

function Field({
  label,
  htmlFor,
  children,
}: {
  label: string;
  htmlFor: string;
  children: React.ReactNode;
}) {
  return (
    <div className="space-y-1.5">
      <label
        htmlFor={htmlFor}
        className="font-mono text-[10px] font-bold uppercase tracking-overline text-rally-muted"
      >
        {label}
      </label>
      {children}
    </div>
  );
}

function roleVariant(role: string): any {
  if (role === "admin") return "enrolled";
  if (role === "coach") return "autopayOn";
  return "manual";
}
