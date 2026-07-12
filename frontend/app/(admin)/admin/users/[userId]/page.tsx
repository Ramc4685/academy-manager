"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { useParams } from "next/navigation";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { AlertTriangle, ArrowLeft, RefreshCw } from "lucide-react";

import {
  addAdminUserRole,
  getAdminUser,
  listAdminSessions,
  listAdminSessionsByCoach,
  listCoachPayRates,
  removeAdminUserRole,
  repairCoachPayRateWindow,
  sendLoginInvite,
  setCoachPayRate,
  updateAdminSession,
  updateAdminUser,
  type AdminSessionView,
  type AdminUserDetail,
  type AdminUserRole,
  type CoachPayBillingUnit,
} from "@/lib/api/admin";
import { rateTimelineIssueLabel } from "@/lib/payroll-warnings";
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
  const isCoach = user.role === "coach";

  const invalidate = () => {
    void queryClient.invalidateQueries({
      queryKey: queryKeys.admin.userDetail(userId),
    });
    void queryClient.invalidateQueries({ queryKey: queryKeys.admin.users() });
  };

  return (
    <section className="space-y-6" data-testid="admin-user-detail">
      <BackLink />
      <Header user={user} />
      <div className="grid gap-6 lg:grid-cols-3">
        <Card p={20} className="lg:col-span-2">
          <Overline>Profile</Overline>
          <UserEditForm user={user} onSaved={invalidate} />
        </Card>
        <Card p={20}>
          <Overline>Access</Overline>
          <RolesPanel user={user} onSaved={invalidate} />
        </Card>
      </div>
      <LoginInvitePanel user={user} onSaved={invalidate} />
      {isCoach && <CoachPayRatePanel coachId={user.user_id} />}
      {isCoach && <CoachSessionsPanel user={user} onAssigned={invalidate} />}
    </section>
  );
}

function CoachPayRatePanel({ coachId }: { coachId: string }) {
  const queryClient = useQueryClient();
  const ratesQuery = useQuery({
    queryKey: ["admin", "coaches", coachId, "pay-rates"],
    queryFn: () => listCoachPayRates(coachId),
    enabled: Boolean(coachId),
  });

  const [billingUnit, setBillingUnit] = useState<CoachPayBillingUnit>("percent_of_revenue");
  const [percent, setPercent] = useState("");
  const [amount, setAmount] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [repairOpen, setRepairOpen] = useState(false);
  const [repairFrom, setRepairFrom] = useState("");
  const [repairUntil, setRepairUntil] = useState("");
  const [repairReason, setRepairReason] = useState("");

  const mutation = useMutation({
    mutationFn: () =>
      setCoachPayRate(coachId, {
        billing_unit: billingUnit,
        percent: billingUnit === "percent_of_revenue" ? Number(percent) : null,
        amount_cents:
          billingUnit === "percent_of_revenue" ? 0 : Math.round(Number(amount) * 100),
      }),
    onSuccess: () => {
      setError(null);
      setPercent("");
      setAmount("");
      void queryClient.invalidateQueries({
        queryKey: ["admin", "coaches", coachId, "pay-rates"],
      });
    },
    onError: (err: unknown) => {
      setError(err instanceof Error ? err.message : "Could not save pay rate.");
    },
  });
  const repairMutation = useMutation({
    mutationFn: () =>
      repairCoachPayRateWindow(coachId, {
        billing_unit: billingUnit,
        percent: billingUnit === "percent_of_revenue" ? Number(percent) : null,
        amount_cents:
          billingUnit === "percent_of_revenue" ? 0 : Math.round(Number(amount) * 100),
        effective_from: repairFrom,
        effective_until: repairUntil,
        reason: repairReason,
      }),
    onSuccess: () => {
      setError(null);
      setRepairOpen(false);
      setRepairReason("");
      void queryClient.invalidateQueries({
        queryKey: ["admin", "coaches", coachId, "pay-rates"],
      });
    },
    onError: (err: unknown) => {
      setError(err instanceof Error ? err.message : "Could not repair pay-rate window.");
    },
  });

  const rates = ratesQuery.data?.rates ?? [];
  const diagnostics = ratesQuery.data?.diagnostics;
  const gap = diagnostics?.issues.find((issue) => issue.issue_type === "gap");
  const active = rates.find((rate) => rate.status === "active") ?? null;
  const isPercent = billingUnit === "percent_of_revenue";
  const valueInvalid = isPercent
    ? !(Number(percent) > 0 && Number(percent) <= 100)
    : !(Number(amount) > 0);
  const repairInvalid = valueInvalid || !repairFrom || !repairUntil || !repairReason.trim();

  return (
    <Card p={20} data-testid="admin-coach-pay-rate">
      <Overline>Pay rate</Overline>
      <div className="mt-3 space-y-4">
        <p className="text-sm text-neutral-600 dark:text-neutral-300">
          {ratesQuery.isLoading
            ? "Loading current pay rate…"
            : active
              ? describeRate(active)
              : "No pay rate set — this coach's sessions will show as unpaid until one is allocated."}
        </p>

        {diagnostics?.issues.length ? (
          <div className="rounded-md border border-amber-200 bg-amber-50 px-3 py-2 text-sm text-amber-900">
            <div className="flex items-center gap-2 font-medium">
              <AlertTriangle className="size-4" aria-hidden="true" />
              Rate timeline needs review
            </div>
            <ul className="mt-2 space-y-1 text-xs">
              {diagnostics.issues.map((issue, index) => (
                <li key={`${issue.issue_type}-${index}`}>
                  <span className="font-medium">{rateTimelineIssueLabel(issue.issue_type)}:</span>{" "}
                  {issue.message}
                </li>
              ))}
            </ul>
            {gap ? (
              <button
                type="button"
                className="mt-2 text-xs font-medium underline"
                onClick={() => {
                  setRepairFrom(gap.starts_at?.slice(0, 10) ?? "");
                  setRepairUntil(gap.ends_at?.slice(0, 10) ?? "");
                  setRepairOpen((open) => !open);
                }}
              >
                Repair rate gap
              </button>
            ) : null}
          </div>
        ) : null}

        <form
          className="flex flex-wrap items-end gap-3"
          onSubmit={(event) => {
            event.preventDefault();
            if (!valueInvalid) mutation.mutate();
          }}
        >
          <label className="flex flex-col gap-1 text-xs font-medium text-neutral-500">
            Pay type
            <select
              value={billingUnit}
              onChange={(event) => setBillingUnit(event.target.value as CoachPayBillingUnit)}
              className="rounded-md border border-neutral-200 px-2 py-1.5 text-sm dark:border-neutral-700 dark:bg-neutral-900"
              data-testid="coach-pay-rate-unit"
            >
              <option value="percent_of_revenue">% of expected session revenue</option>
              <option value="per_session">Fixed per session</option>
              <option value="per_hour">Fixed per hour</option>
            </select>
          </label>
          {isPercent ? (
            <label className="flex flex-col gap-1 text-xs font-medium text-neutral-500">
              Percent
              <input
                type="number"
                min={0}
                max={100}
                step="0.5"
                value={percent}
                onChange={(event) => setPercent(event.target.value)}
                placeholder="60"
                className="w-24 rounded-md border border-neutral-200 px-2 py-1.5 text-sm dark:border-neutral-700 dark:bg-neutral-900"
                data-testid="coach-pay-rate-percent"
              />
              <span className="max-w-xs text-[11px] font-normal text-neutral-500">
                Basis: <span className="font-medium">expected</span> session revenue
                (session price × active enrollments) — billed revenue, not cash collected.
              </span>
              <span className="max-w-xs text-[11px] font-normal text-amber-700">
                Percent pay requires every assigned active session to have a session price.
                Use $0 only for an explicitly free session.
              </span>
            </label>
          ) : (
            <label className="flex flex-col gap-1 text-xs font-medium text-neutral-500">
              Amount (USD)
              <input
                type="number"
                min={0}
                step="0.01"
                value={amount}
                onChange={(event) => setAmount(event.target.value)}
                placeholder="50.00"
                className="w-28 rounded-md border border-neutral-200 px-2 py-1.5 text-sm dark:border-neutral-700 dark:bg-neutral-900"
                data-testid="coach-pay-rate-amount"
              />
            </label>
          )}
          <Button
            type="submit"
            disabled={valueInvalid || mutation.isPending}
            data-testid="coach-pay-rate-save"
          >
            {mutation.isPending ? "Saving…" : "Set pay rate"}
          </Button>
        </form>

        {repairOpen ? (
          <form
            className="rounded-md border border-neutral-200 p-3 dark:border-neutral-800"
            onSubmit={(event) => {
              event.preventDefault();
              if (!repairInvalid) repairMutation.mutate();
            }}
          >
            <div className="grid gap-3 sm:grid-cols-3">
              <label className="flex flex-col gap-1 text-xs font-medium text-neutral-500">
                From
                <input
                  type="date"
                  value={repairFrom}
                  onChange={(event) => setRepairFrom(event.target.value)}
                  className="rounded-md border border-neutral-200 px-2 py-1.5 text-sm dark:border-neutral-700 dark:bg-neutral-900"
                />
              </label>
              <label className="flex flex-col gap-1 text-xs font-medium text-neutral-500">
                Until
                <input
                  type="date"
                  value={repairUntil}
                  onChange={(event) => setRepairUntil(event.target.value)}
                  className="rounded-md border border-neutral-200 px-2 py-1.5 text-sm dark:border-neutral-700 dark:bg-neutral-900"
                />
              </label>
              <label className="flex flex-col gap-1 text-xs font-medium text-neutral-500">
                Reason
                <input
                  value={repairReason}
                  onChange={(event) => setRepairReason(event.target.value)}
                  className="rounded-md border border-neutral-200 px-2 py-1.5 text-sm dark:border-neutral-700 dark:bg-neutral-900"
                />
              </label>
            </div>
            <div className="mt-3 flex gap-2">
              <Button type="submit" disabled={repairInvalid || repairMutation.isPending}>
                {repairMutation.isPending ? "Repairing…" : "Save repair"}
              </Button>
              <Button type="button" variant="secondary" onClick={() => setRepairOpen(false)}>
                Cancel
              </Button>
            </div>
          </form>
        ) : null}

        {error ? (
          <p role="alert" className="text-sm text-red-600">
            {error}
          </p>
        ) : null}

        {rates.length > 0 ? (
          <div className="border-t border-neutral-100 pt-3 dark:border-neutral-800">
            <p className="mb-1 text-xs font-medium uppercase tracking-wide text-neutral-500">
              History
            </p>
            <ul className="space-y-1 text-xs text-neutral-500">
              {rates.map((rate) => (
                <li key={rate.rate_id}>
                  {describeRate(rate)} · from{" "}
                  {new Date(rate.effective_from).toLocaleDateString()}
                  {rate.effective_until
                    ? ` until ${new Date(rate.effective_until).toLocaleDateString()}`
                    : ""}{" "}
                  · {rate.status}
                </li>
              ))}
            </ul>
          </div>
        ) : null}
      </div>
    </Card>
  );
}

function describeRate(rate: {
  billing_unit: CoachPayBillingUnit;
  percent: number | null;
  amount_cents: number;
  currency: string;
}): string {
  if (rate.billing_unit === "percent_of_revenue") {
    return `${rate.percent ?? 0}% of expected session revenue`;
  }
  const amount = (rate.amount_cents / 100).toLocaleString("en-US", {
    style: "currency",
    currency: rate.currency || "USD",
  });
  return rate.billing_unit === "per_session" ? `${amount} per session` : `${amount} per hour`;
}

function StateCard({
  message,
  isError = false,
}: {
  message: string;
  isError?: boolean;
}) {
  return (
    <section className="space-y-4">
      <BackLink />
      <Card p={20}>
        <p
          role={isError ? "alert" : undefined}
          className="text-sm text-rally-muted"
        >
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
              <Chip
                variant={roleVariant(user.role)}
                label={user.role.toUpperCase()}
              />
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

function UserEditForm({
  user,
  onSaved,
}: {
  user: AdminUserDetail;
  onSaved: () => void;
}) {
  const [email, setEmail] = useState(user.email);
  const [displayName, setDisplayName] = useState(user.display_name);
  const [phone, setPhone] = useState(user.phone ?? "");
  const [status, setStatus] = useState(user.status);
  const [reason, setReason] = useState("Admin user update");
  const [submitError, setSubmitError] = useState<string | null>(null);
  const [submitOk, setSubmitOk] = useState(false);

  useEffect(() => {
    setEmail(user.email);
    setDisplayName(user.display_name);
    setPhone(user.phone ?? "");
    setStatus(user.status);
  }, [user.email, user.display_name, user.phone, user.status]);

  const mutation = useMutation({
    mutationFn: () =>
      updateAdminUser(user.user_id, {
        email: email !== user.email ? email : undefined,
        display_name:
          displayName !== user.display_name ? displayName : undefined,
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
      setSubmitError(
        err instanceof Error ? err.message : "Could not save user.",
      );
    },
  });

  const dirty =
    email !== user.email ||
    displayName !== user.display_name ||
    phone !== (user.phone ?? "") ||
    status !== user.status;

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
      <Field label="Email" htmlFor="user-email">
        <input
          id="user-email"
          type="email"
          value={email}
          onChange={(event) => setEmail(event.target.value)}
          className="h-10 w-full rounded-md border border-neutral-200 bg-white px-3 text-sm text-rally-base outline-none focus:border-rally-cobalt-600 focus:ring-2 focus:ring-rally-cobalt-600/15"
          required
          maxLength={254}
        />
      </Field>

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
          icon={
            mutation.isPending ? (
              <RefreshCw className="size-3.5 animate-spin" />
            ) : undefined
          }
        >
          {mutation.isPending ? "Saving..." : "Save changes"}
        </Button>
        {dirty && (
          <Button
            type="button"
            variant="secondary"
            size="sm"
            onClick={() => {
              setEmail(user.email);
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

function RolesPanel({
  user,
  onSaved,
}: {
  user: AdminUserDetail;
  onSaved: () => void;
}) {
  const initialRoles = user.roles.length > 0 ? user.roles : [user.role];
  const [selected, setSelected] = useState<AdminUserRole[]>(initialRoles);
  const [reason, setReason] = useState("Admin role change");
  const [submitError, setSubmitError] = useState<string | null>(null);
  const [submitOk, setSubmitOk] = useState(false);

  useEffect(() => {
    setSelected(user.roles.length > 0 ? user.roles : [user.role]);
  }, [user.roles, user.role]);

  const mutation = useMutation({
    mutationFn: async () => {
      const current = new Set(initialRoles);
      const next = new Set(selected);
      for (const role of academyRoles) {
        if (next.has(role) && !current.has(role)) {
          await addAdminUserRole(user.user_id, role, reason);
        }
      }
      for (const role of academyRoles) {
        if (current.has(role) && !next.has(role)) {
          await removeAdminUserRole(user.user_id, role, reason);
        }
      }
    },
    onSuccess: () => {
      setSubmitError(null);
      setSubmitOk(true);
      onSaved();
    },
    onError: (err: unknown) => {
      setSubmitOk(false);
      setSubmitError(err instanceof Error ? err.message : "Could not update roles.");
    },
  });

  const toggle = (role: AdminUserRole) => {
    setSubmitOk(false);
    setSelected((prev) =>
      prev.includes(role) ? prev.filter((r) => r !== role) : [...prev, role],
    );
  };

  return (
    <form
      className="mt-3 space-y-4"
      data-testid="admin-user-role-form"
      onSubmit={(e) => {
        e.preventDefault();
        setSubmitOk(false);
        setSubmitError(null);
        if (selected.length === 0) {
          setSubmitError("User must keep at least one role.");
          return;
        }
        mutation.mutate();
      }}
    >
      <p className="text-xs text-rally-muted">
        A user can hold multiple roles — e.g. an admin who also coaches, or a
        coach who is also a parent. Users with more than one role get a view
        switcher in the app header.
      </p>
      <div className="flex flex-wrap gap-3">
        {academyRoles.map((role) => (
          <label key={role} className="inline-flex items-center gap-2 text-sm">
            <input
              type="checkbox"
              checked={selected.includes(role)}
              onChange={() => toggle(role)}
              data-testid={`role-checkbox-${role}`}
            />
            <span className="capitalize">{role}</span>
          </label>
        ))}
      </div>

      <Field label="Reason" htmlFor="user-role-reason">
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
        disabled={mutation.isPending}
        icon={
          mutation.isPending ? (
            <RefreshCw className="size-3.5 animate-spin" />
          ) : undefined
        }
      >
        {mutation.isPending ? "Saving..." : "Save roles"}
      </Button>
    </form>
  );
}

function LoginInvitePanel({
  user,
  onSaved,
}: {
  user: AdminUserDetail;
  onSaved: () => void;
}) {
  const [submitError, setSubmitError] = useState<string | null>(null);
  const [submitOk, setSubmitOk] = useState(false);

  const mutation = useMutation({
    mutationFn: () => sendLoginInvite(user.user_id),
    onSuccess: () => {
      setSubmitError(null);
      setSubmitOk(true);
      onSaved();
    },
    onError: (err: unknown) => {
      setSubmitOk(false);
      setSubmitError(err instanceof Error ? err.message : "Could not send invite.");
    },
  });

  return (
    <section className="space-y-3 rounded-lg border border-rally-line bg-white p-4">
      <h2 className="text-sm font-semibold text-rally-ink">Login invite</h2>
      <p className="text-xs text-slate-500">
        Sends a &ldquo;set your password&rdquo; email so this user can log in
        with email + password (works with any email provider).
      </p>
      <p className="text-sm text-slate-600" data-testid="invite-sent-at">
        {user.login_invite_sent_at
          ? `Invite sent ${new Date(user.login_invite_sent_at).toLocaleDateString()}`
          : "No invite sent yet"}
      </p>
      <MutationMessages error={submitError} ok={submitOk} />
      <Button
        type="button"
        size="sm"
        variant="secondary"
        disabled={mutation.isPending}
        onClick={() => mutation.mutate()}
        data-testid="send-login-invite"
      >
        {mutation.isPending
          ? "Sending…"
          : user.login_invite_sent_at
            ? "Re-send invite"
            : "Send login invite"}
      </Button>
    </section>
  );
}

function CoachSessionsPanel({
  user,
  onAssigned,
}: {
  user: AdminUserDetail;
  onAssigned: () => void;
}) {
  const queryClient = useQueryClient();
  const [assignSessionId, setAssignSessionId] = useState("");
  const [assignReason, setAssignReason] = useState("Admin coach assignment");
  const [assignError, setAssignError] = useState<string | null>(null);
  const [assignOk, setAssignOk] = useState(false);

  const coachSessionsQuery = useQuery({
    queryKey: queryKeys.admin.coachSessions(user.user_id),
    queryFn: () => listAdminSessionsByCoach(user.user_id),
  });

  const allSessionsQuery = useQuery({
    queryKey: queryKeys.admin.sessions(),
    queryFn: () => listAdminSessions(undefined, { window: "upcoming" }),
  });

  const assignMutation = useMutation({
    mutationFn: () =>
      updateAdminSession(assignSessionId, {
        coach_id: user.user_id,
        reason: assignReason,
      }),
    onSuccess: () => {
      setAssignError(null);
      setAssignOk(true);
      setAssignSessionId("");
      void queryClient.invalidateQueries({
        queryKey: queryKeys.admin.coachSessions(user.user_id),
      });
      void queryClient.invalidateQueries({
        queryKey: queryKeys.admin.sessions(),
      });
      void queryClient.invalidateQueries({
        queryKey: queryKeys.admin.userDetail(user.user_id),
      });
      onAssigned();
    },
    onError: (err: unknown) => {
      setAssignOk(false);
      setAssignError(
        err instanceof Error ? err.message : "Could not assign session.",
      );
    },
  });

  const coachSessions = coachSessionsQuery.data?.sessions ?? [];
  const allSessions = allSessionsQuery.data?.sessions ?? [];
  const availableSessions = allSessions.filter(
    (s) => s.coach_id !== user.user_id,
  );

  const fmt = (iso: string) =>
    new Date(iso).toLocaleString(undefined, {
      weekday: "short",
      month: "short",
      day: "numeric",
      hour: "numeric",
      minute: "2-digit",
    });

  return (
    <Card p={20}>
      <Overline>Coach Sessions</Overline>

      <div className="mt-4 space-y-6">
        <div>
          <p className="mb-2 text-xs font-semibold uppercase tracking-wider text-rally-muted">
            Assigned sessions ({coachSessions.length})
          </p>
          {coachSessionsQuery.isPending ? (
            <div className="h-12 animate-pulse rounded-md bg-neutral-100" />
          ) : coachSessions.length === 0 ? (
            <p className="text-sm text-rally-muted">
              No sessions assigned to this coach.
            </p>
          ) : (
            <ul className="divide-y divide-neutral-100 rounded-md border border-neutral-200">
              {coachSessions.map((session) => (
                <SessionRow
                  key={session.session_id}
                  session={session}
                  fmt={fmt}
                />
              ))}
            </ul>
          )}
        </div>

        <div>
          <p className="mb-2 text-xs font-semibold uppercase tracking-wider text-rally-muted">
            Assign a session to this coach
          </p>
          <form
            className="space-y-3"
            onSubmit={(e) => {
              e.preventDefault();
              setAssignOk(false);
              setAssignError(null);
              assignMutation.mutate();
            }}
          >
            <Field label="Session" htmlFor="assign-session">
              <select
                id="assign-session"
                value={assignSessionId}
                onChange={(e) => setAssignSessionId(e.target.value)}
                className="h-10 w-full rounded-md border border-neutral-200 bg-white px-3 text-sm text-rally-base outline-none focus:border-rally-cobalt-600 focus:ring-2 focus:ring-rally-cobalt-600/15"
                required
              >
                <option value="">Select a session…</option>
                {availableSessions.map((s) => (
                  <option key={s.session_id} value={s.session_id}>
                    {s.title} — {fmt(s.start_at)} ({s.enrolled_count} students)
                  </option>
                ))}
              </select>
            </Field>

            <Field label="Reason" htmlFor="assign-reason">
              <input
                id="assign-reason"
                value={assignReason}
                onChange={(e) => setAssignReason(e.target.value)}
                className="h-10 w-full rounded-md border border-neutral-200 bg-white px-3 text-sm text-rally-base outline-none focus:border-rally-cobalt-600 focus:ring-2 focus:ring-rally-cobalt-600/15"
                required
                maxLength={500}
              />
            </Field>

            <MutationMessages error={assignError} ok={assignOk} />

            <Button
              type="submit"
              variant="primary"
              size="sm"
              disabled={!assignSessionId || assignMutation.isPending}
              icon={
                assignMutation.isPending ? (
                  <RefreshCw className="size-3.5 animate-spin" />
                ) : undefined
              }
            >
              {assignMutation.isPending ? "Assigning…" : "Assign to coach"}
            </Button>
          </form>
        </div>
      </div>
    </Card>
  );
}

function SessionRow({
  session,
  fmt,
}: {
  session: AdminSessionView;
  fmt: (iso: string) => string;
}) {
  return (
    <li className="flex items-center justify-between px-3 py-2.5 text-sm">
      <div className="min-w-0">
        <p className="truncate font-medium text-rally-ink">{session.title}</p>
        <p className="truncate text-xs text-rally-muted">
          {fmt(session.start_at)}
        </p>
      </div>
      <div className="ml-4 shrink-0 text-right text-xs text-rally-muted">
        <span>{session.enrolled_count} enrolled</span>
        <Link
          href={`/admin/sessions/${session.session_id}`}
          className="ml-3 text-rally-cobalt-600 hover:underline"
        >
          View
        </Link>
      </div>
    </li>
  );
}

function MutationMessages({
  error,
  ok,
}: {
  error: string | null;
  ok: boolean;
}) {
  return (
    <>
      {error && (
        <p
          role="alert"
          className="rounded-md border border-red-200 bg-red-50 p-2 text-sm text-red-700"
        >
          {error}
        </p>
      )}
      {ok && (
        <p
          role="status"
          className="rounded-md border border-emerald-200 bg-emerald-50 p-2 text-sm text-emerald-800"
        >
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
