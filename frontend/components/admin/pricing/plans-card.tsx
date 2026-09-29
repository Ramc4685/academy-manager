"use client";

import { useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import {
  archiveSessionType,
  createSessionType,
  listSessionTypes,
  updateSessionType,
  type CreateSessionTypeRequest,
  type SessionTypeView,
  type UpdateSessionTypeRequest,
} from "@/lib/api/v2/session-types";
import { PLAN_TYPE_LABEL } from "@/lib/api/v2/pricing";
import { queryKeys } from "@/lib/query/keys";
import {
  Button,
  Card,
  Chip,
  DialogActions,
  DialogError,
  EmptyState,
  FormField,
  Modal,
  Overline,
  TableSkeleton,
  Th,
} from "@/components/ds";
import { OwnerOnlyHint, useIsOwner } from "@/components/admin/owner-context";

interface FormState {
  name: string;
  description: string;
  price: string;
  overage_rate: string;
}

const BLANK_FORM: FormState = {
  name: "",
  description: "",
  price: "",
  overage_rate: "",
};

function formatMoney(cents: number | null): string {
  if (cents === null) return "—";
  return `$${(cents / 100).toFixed(2)}`;
}

function dollarsToCents(value: string): number | null {
  const trimmed = value.trim();
  if (trimmed === "") return null;
  const parsed = Number(trimmed);
  if (!Number.isFinite(parsed)) return null;
  return Math.round(parsed * 100);
}

function centsToDollars(cents: number | null): string {
  return cents === null ? "" : (cents / 100).toFixed(2);
}

function toFormState(sessionType: SessionTypeView): FormState {
  return {
    name: sessionType.name,
    description: sessionType.description ?? "",
    price: centsToDollars(sessionType.price_cents),
    overage_rate: centsToDollars(sessionType.overage_rate_cents),
  };
}

function validate(form: FormState): Partial<Record<keyof FormState, string>> {
  const errors: Partial<Record<keyof FormState, string>> = {};
  const name = form.name.trim();
  if (!name) errors.name = "Name is required.";
  else if (name.length > 120) errors.name = "Name must be 120 characters or fewer.";
  if (form.description.trim().length > 500) {
    errors.description = "Description must be 500 characters or fewer.";
  }
  const price = dollarsToCents(form.price);
  if (price === null) errors.price = "Price is required.";
  else if (price < 0) errors.price = "Price cannot be negative.";
  if (form.overage_rate.trim() !== "") {
    const overage = dollarsToCents(form.overage_rate);
    if (overage === null) errors.overage_rate = "Enter a valid amount.";
    else if (overage < 0) errors.overage_rate = "Overage rate cannot be negative.";
  }
  return errors;
}

function toCreatePayload(form: FormState): CreateSessionTypeRequest {
  return {
    name: form.name.trim(),
    description: form.description.trim() || null,
    price_cents: dollarsToCents(form.price) ?? 0,
    // Only monthly plans can be saved for now (Settings overhaul PR 11b).
    plan_type: "monthly",
    overage_rate_cents: dollarsToCents(form.overage_rate),
  };
}

/** Only send fields the admin actually changed, so PATCH stays minimal. */
function toUpdatePayload(original: FormState, form: FormState): UpdateSessionTypeRequest {
  const payload: UpdateSessionTypeRequest = {};
  if (form.name.trim() !== original.name.trim()) payload.name = form.name.trim();
  if (form.description.trim() !== original.description.trim()) {
    payload.description = form.description.trim() || null;
  }
  if (form.price !== original.price) payload.price_cents = dollarsToCents(form.price) ?? 0;
  if (form.overage_rate !== original.overage_rate) {
    payload.overage_rate_cents = dollarsToCents(form.overage_rate);
  }
  return payload;
}

/**
 * Plans: the academy price list (stored as session types), shown on the
 * Pricing page under Money. It was the Settings "Session types" tab until
 * Settings overhaul PR 11b.
 *
 * Archive is a soft delete. `GET /admin/session-types` hides archived rows
 * unless `include_archived=true`, so the toggle below is what makes a
 * soft-deleted plan reachable again; Reactivate is `PATCH is_active: true`.
 *
 * Every write is owner-only (Settings overhaul Phase 1 PR 5). A plan price
 * is not what a class is charged: every class keeps its own monthly fee, so
 * editing a plan never changes a bill.
 */
export function PlansCard({ linkedCounts }: { linkedCounts?: Record<string, number> }) {
  const queryClient = useQueryClient();
  const isOwner = useIsOwner();
  const [editing, setEditing] = useState<SessionTypeView | "new" | null>(null);
  const [archiving, setArchiving] = useState<SessionTypeView | null>(null);
  const [showArchived, setShowArchived] = useState(false);

  const query = useQuery({
    queryKey: queryKeys.admin.sessionTypesList(showArchived),
    queryFn: () => listSessionTypes({ includeArchived: showArchived }),
    retry: false,
  });

  // A plan change moves the class links and counts on the rest of the page.
  const invalidate = () =>
    Promise.all([
      queryClient.invalidateQueries({ queryKey: queryKeys.admin.sessionTypes() }),
      queryClient.invalidateQueries({ queryKey: queryKeys.admin.pricing() }),
    ]);

  const archiveMutation = useMutation({
    mutationFn: (sessionTypeId: string) => archiveSessionType(sessionTypeId),
    onSuccess: () => {
      setArchiving(null);
      void invalidate();
    },
  });

  // One mutation serves every row, so its error state has to be cleared when
  // the dialog is aimed at a different session type.
  function openArchive(row: SessionTypeView | null) {
    archiveMutation.reset();
    setArchiving(row);
  }

  // Restoring an archived type is just clearing the soft-delete flag. One
  // mutation serves every row; `variables` (the id in flight) is what scopes
  // the pending and error states to the row that was actually clicked.
  const reactivateMutation = useMutation({
    mutationFn: (sessionTypeId: string) =>
      updateSessionType(sessionTypeId, { is_active: true }),
    onSuccess: () => void invalidate(),
  });

  const rows = query.data?.session_types ?? [];

  return (
    <section data-testid="pricing-plans" className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <Overline>Plans</Overline>
          <p className="mt-1 text-sm text-rally-muted">
            Your price list. Each class keeps its own monthly fee; a plan shows where it
            comes from.
          </p>
        </div>
        <div className="flex items-center gap-4">
          <label className="flex items-center gap-2 text-sm text-rally-muted">
            <input
              type="checkbox"
              checked={showArchived}
              onChange={(event) => setShowArchived(event.target.checked)}
              data-testid="session-types-show-archived"
              className="h-4 w-4 rounded border-rally-line"
            />
            Show archived
          </label>
          {isOwner ? (
            <Button
              variant="volt"
              size="sm"
              onClick={() => setEditing("new")}
              data-testid="session-type-new"
            >
              New plan
            </Button>
          ) : (
            <OwnerOnlyHint />
          )}
        </div>
      </div>

      <Card p={0}>
        {query.isPending ? (
          <div className="p-5">
            <TableSkeleton rows={4} cols={4} />
          </div>
        ) : query.isError ? (
          <p
            role="alert"
            data-testid="session-types-error"
            className="p-5 text-sm text-status-red-800"
          >
            Could not load plans.
          </p>
        ) : rows.length === 0 ? (
          <EmptyState
            data-testid="session-types-empty"
            title={showArchived ? "No plans" : "No active plans"}
            description={
              showArchived
                ? "Add a plan for each price you charge, like a group class or a private lesson."
                : "Nothing active. Tick \u201cShow archived\u201d to look for one you archived."
            }
            action={
              isOwner ? (
                <Button variant="volt" size="sm" onClick={() => setEditing("new")}>
                  New plan
                </Button>
              ) : undefined
            }
          />
        ) : (
          <PlansTable
            rows={rows}
            linkedCounts={linkedCounts}
            canEdit={isOwner}
            onEdit={setEditing}
            onArchive={openArchive}
            onReactivate={(row) => reactivateMutation.mutate(row.session_type_id)}
            reactivatingId={
              reactivateMutation.isPending ? (reactivateMutation.variables ?? null) : null
            }
            failedReactivateId={
              reactivateMutation.isError ? (reactivateMutation.variables ?? null) : null
            }
          />
        )}
      </Card>

      {editing && (
        <SessionTypeDialog
          sessionType={editing === "new" ? null : editing}
          onClose={() => setEditing(null)}
          onSaved={() => {
            setEditing(null);
            void invalidate();
          }}
        />
      )}

      {archiving && (
        <Modal
          open
          onClose={() => openArchive(null)}
          title={`Archive "${archiving.name}"?`}
          size="sm"
        >
          <p className="text-sm text-rally-muted">
            Students already enrolled keep billing at their current price. Archiving
            does not stop or change them, and classes linked to it show as Custom. To
            bring it back, tick “Show archived” and reactivate it.
          </p>
          {archiveMutation.isError && (
            <div className="mt-3">
              <DialogError message="Could not archive this plan. Try again." />
            </div>
          )}
          <DialogActions>
            <Button variant="secondary" size="sm" onClick={() => openArchive(null)}>
              Cancel
            </Button>
            <Button
              variant="danger"
              size="sm"
              disabled={archiveMutation.isPending}
              onClick={() => archiveMutation.mutate(archiving.session_type_id)}
              data-testid="session-type-archive-confirm"
            >
              {archiveMutation.isPending ? "Archiving..." : "Archive"}
            </Button>
          </DialogActions>
        </Modal>
      )}
    </section>
  );
}

export function PlansTable({
  rows,
  linkedCounts,
  canEdit,
  onEdit,
  onArchive,
  onReactivate,
  reactivatingId,
  failedReactivateId,
}: {
  rows: SessionTypeView[];
  /** Classes linked to each plan, from the Pricing overview. */
  linkedCounts?: Record<string, number>;
  /** False for an admin without the owner scope: prices are read-only. */
  canEdit: boolean;
  onEdit: (row: SessionTypeView) => void;
  onArchive: (row: SessionTypeView) => void;
  onReactivate: (row: SessionTypeView) => void;
  /** Id of the row whose reactivation is in flight, so only it shows pending. */
  reactivatingId: string | null;
  failedReactivateId: string | null;
}) {
  return (
    <div className="overflow-x-auto">
      <table className="w-full min-w-[640px] text-sm">
        <thead>
          <tr className="border-b border-rally-line">
            <Th>Plan</Th>
            <Th>Price</Th>
            <Th>Type</Th>
            <Th align="right">Classes</Th>
            <Th align="right">Actions</Th>
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => (
            <tr
              key={row.session_type_id}
              data-testid="session-type-row"
              data-archived={row.is_active ? undefined : "true"}
              className={`border-b border-rally-line last:border-0 ${
                row.is_active ? "" : "bg-rally-paper text-rally-muted"
              }`}
            >
              <td className="px-4 py-3">
                <span
                  className={
                    row.is_active ? "font-semibold text-rally-ink" : "font-semibold"
                  }
                >
                  {row.name}
                </span>
                {!row.is_active && (
                  <span className="ml-2 align-middle">
                    <Chip variant="expired" label="ARCHIVED" />
                  </span>
                )}
                {row.description && (
                  <p className="text-xs text-rally-subtle">{row.description}</p>
                )}
                {failedReactivateId === row.session_type_id && (
                  <p role="alert" className="mt-1 text-xs text-status-red-800">
                    Could not reactivate this plan. Try again.
                  </p>
                )}
              </td>
              <td className="px-4 py-3 font-mono tabular-nums">
                {formatMoney(row.price_cents)}
                <span className="font-sans text-xs text-rally-subtle"> / month</span>
              </td>
              <td className="px-4 py-3" data-testid="plan-type">
                {PLAN_TYPE_LABEL[row.plan_type ?? "monthly"]}
                {row.billing_period === "per_session" && (
                  <p className="text-xs text-rally-subtle" data-testid="plan-legacy-period">
                    Saved earlier as per session. Billing still uses the class fee.
                  </p>
                )}
              </td>
              <td
                className="px-4 py-3 text-right font-mono tabular-nums"
                data-testid="plan-linked-classes"
              >
                {linkedCounts?.[row.session_type_id] ?? 0}
              </td>
              <td className="px-4 py-3">
                <div className="flex justify-end gap-2">
                  {!canEdit ? (
                    <OwnerOnlyHint />
                  ) : (
                    <Button variant="secondary" size="sm" onClick={() => onEdit(row)}>
                      Edit
                    </Button>
                  )}
                  {!canEdit ? null : row.is_active ? (
                    <Button variant="danger" size="sm" onClick={() => onArchive(row)}>
                      Archive
                    </Button>
                  ) : (
                    <Button
                      variant="volt"
                      size="sm"
                      disabled={reactivatingId === row.session_type_id}
                      onClick={() => onReactivate(row)}
                      data-testid="session-type-reactivate"
                    >
                      {reactivatingId === row.session_type_id
                        ? "Reactivating..."
                        : "Reactivate"}
                    </Button>
                  )}
                </div>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function SessionTypeDialog({
  sessionType,
  onClose,
  onSaved,
}: {
  sessionType: SessionTypeView | null;
  onClose: () => void;
  onSaved: () => void;
}) {
  const original = useMemo(
    () => (sessionType ? toFormState(sessionType) : BLANK_FORM),
    [sessionType],
  );
  const [form, setForm] = useState<FormState>(original);
  const [submitted, setSubmitted] = useState(false);

  const errors = validate(form);
  const shown = submitted ? errors : {};

  const mutation = useMutation({
    mutationFn: () =>
      sessionType
        ? updateSessionType(sessionType.session_type_id, toUpdatePayload(original, form))
        : createSessionType(toCreatePayload(form)),
    onSuccess: onSaved,
  });

  function set<K extends keyof FormState>(key: K, value: FormState[K]) {
    setForm((prev) => ({ ...prev, [key]: value }));
  }

  function submit() {
    setSubmitted(true);
    if (Object.keys(errors).length > 0) return;
    mutation.mutate();
  }

  return (
    <Modal
      open
      onClose={onClose}
      title={sessionType ? `Edit ${sessionType.name}` : "New plan"}
      size="md"
    >
      <form
        onSubmit={(event) => {
          event.preventDefault();
          submit();
        }}
      >
        <div className="space-y-4">
          {mutation.isError && (
            <DialogError message="Could not save this plan. Check the values and try again." />
          )}
          {sessionType && (
            <p className="rounded-md bg-status-amber-50 px-3 py-2 text-xs text-status-amber-800">
              Classes keep their own monthly fee, so a new price here does not change what
              any family pays. Classes linked to this plan show as Custom until their fee
              matches again.
            </p>
          )}
          <FormField label="Name" htmlFor="st-name" error={shown.name} required>
            <input
              id="st-name"
              value={form.name}
              maxLength={120}
              onChange={(event) => set("name", event.target.value)}
              className="h-10 w-full rounded-md border border-rally-line px-3 text-sm outline-none focus:border-blue-500"
            />
          </FormField>
          <FormField label="Description" htmlFor="st-description" error={shown.description}>
            <textarea
              id="st-description"
              value={form.description}
              maxLength={500}
              rows={2}
              onChange={(event) => set("description", event.target.value)}
              className="w-full rounded-md border border-rally-line px-3 py-2 text-sm outline-none focus:border-blue-500"
            />
          </FormField>
          <div className="grid gap-4 sm:grid-cols-2">
            <FormField label="Price ($)" htmlFor="st-price" error={shown.price} required>
              <input
                id="st-price"
                type="number"
                min="0"
                step="0.01"
                inputMode="decimal"
                value={form.price}
                onChange={(event) => set("price", event.target.value)}
                className="h-10 w-full rounded-md border border-rally-line px-3 font-mono text-sm tabular-nums outline-none focus:border-blue-500"
              />
            </FormField>
            <FormField
              label="Plan type"
              htmlFor="st-plan-type"
              hint="The fee buys 4 classes per weekly slot; a 5th date in the month is free."
            >
              <select
                id="st-plan-type"
                value="monthly"
                onChange={() => undefined}
                className="h-10 w-full rounded-md border border-rally-line px-3 text-sm outline-none focus:border-blue-500"
              >
                <option value="monthly">{PLAN_TYPE_LABEL.monthly}</option>
                <option value="per_session" disabled>
                  Per session - coming later
                </option>
              </select>
            </FormField>
          </div>
          <FormField
            label="Overage rate ($)"
            htmlFor="st-overage"
            error={shown.overage_rate}
            hint="Charged per session beyond the plan's included sessions. Leave blank for none."
          >
            <input
              id="st-overage"
              type="number"
              min="0"
              step="0.01"
              inputMode="decimal"
              value={form.overage_rate}
              onChange={(event) => set("overage_rate", event.target.value)}
              className="h-10 w-full rounded-md border border-rally-line px-3 font-mono text-sm tabular-nums outline-none focus:border-blue-500"
            />
          </FormField>
        </div>
        <DialogActions>
          <Button variant="secondary" size="sm" onClick={onClose}>
            Cancel
          </Button>
          <Button
            type="submit"
            variant="volt"
            size="sm"
            disabled={mutation.isPending}
            data-testid="session-type-save"
          >
            {mutation.isPending ? "Saving..." : "Save"}
          </Button>
        </DialogActions>
      </form>
    </Modal>
  );
}
