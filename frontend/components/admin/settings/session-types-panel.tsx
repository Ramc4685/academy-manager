"use client";

import { useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import {
  archiveSessionType,
  createSessionType,
  listSessionTypes,
  updateSessionType,
  type CreateSessionTypeRequest,
  type SessionTypeBillingPeriod,
  type SessionTypeView,
  type UpdateSessionTypeRequest,
} from "@/lib/api/v2/session-types";
import { queryKeys } from "@/lib/query/keys";
import {
  Button,
  Card,
  DialogActions,
  DialogError,
  EmptyState,
  FormField,
  Modal,
  Overline,
  TableSkeleton,
  Th,
} from "@/components/ds";

const PERIOD_LABEL: Record<SessionTypeBillingPeriod, string> = {
  monthly: "Monthly",
  per_session: "Per session",
};

interface FormState {
  name: string;
  description: string;
  price: string;
  billing_period: SessionTypeBillingPeriod;
  overage_rate: string;
}

const BLANK_FORM: FormState = {
  name: "",
  description: "",
  price: "",
  billing_period: "monthly",
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
    billing_period: sessionType.billing_period,
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
    billing_period: form.billing_period,
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
  if (form.billing_period !== original.billing_period) {
    payload.billing_period = form.billing_period;
  }
  if (form.overage_rate !== original.overage_rate) {
    payload.overage_rate_cents = dollarsToCents(form.overage_rate);
  }
  return payload;
}

/**
 * Session types are the pricing catalog behind billing enrollments.
 *
 * Archive is a soft delete, and `GET /admin/session-types` only returns
 * active rows (`SessionTypeRepository.list_active`), so archived types are
 * neither listable nor restorable from here — the confirm copy says so.
 */
export function SessionTypesPanel() {
  const queryClient = useQueryClient();
  const [editing, setEditing] = useState<SessionTypeView | "new" | null>(null);
  const [archiving, setArchiving] = useState<SessionTypeView | null>(null);

  const query = useQuery({
    queryKey: queryKeys.admin.sessionTypes(),
    queryFn: listSessionTypes,
    retry: false,
  });

  const invalidate = () =>
    queryClient.invalidateQueries({ queryKey: queryKeys.admin.sessionTypes() });

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

  const rows = query.data?.session_types ?? [];

  return (
    <section data-testid="admin-settings-session-types" className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <Overline>Billing catalog</Overline>
          <p className="mt-1 text-sm text-rally-muted">
            Pricing plans students are billed against.
          </p>
        </div>
        <Button
          variant="volt"
          size="sm"
          onClick={() => setEditing("new")}
          data-testid="session-type-new"
        >
          New session type
        </Button>
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
            Could not load session types.
          </p>
        ) : rows.length === 0 ? (
          <EmptyState
            data-testid="session-types-empty"
            title="No session types yet"
            description="Create a session type to start billing enrollments against a price."
            action={
              <Button variant="volt" size="sm" onClick={() => setEditing("new")}>
                New session type
              </Button>
            }
          />
        ) : (
          <SessionTypesTable rows={rows} onEdit={setEditing} onArchive={openArchive} />
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
            Students already enrolled keep billing at their current price — archiving
            does not stop or change them. New enrollments can no longer choose this
            plan, and it cannot be restored from this screen.
          </p>
          {archiveMutation.isError && (
            <div className="mt-3">
              <DialogError message="Could not archive this session type. Try again." />
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

function SessionTypesTable({
  rows,
  onEdit,
  onArchive,
}: {
  rows: SessionTypeView[];
  onEdit: (row: SessionTypeView) => void;
  onArchive: (row: SessionTypeView) => void;
}) {
  return (
    <div className="overflow-x-auto">
      <table className="w-full min-w-[640px] text-sm">
        <thead>
          <tr className="border-b border-rally-line">
            <Th>Name</Th>
            <Th>Price</Th>
            <Th>Billing</Th>
            <Th>Overage</Th>
            <Th align="right">Actions</Th>
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => (
            <tr
              key={row.session_type_id}
              data-testid="session-type-row"
              className="border-b border-rally-line last:border-0"
            >
              <td className="px-4 py-3">
                <span className="font-semibold text-rally-ink">{row.name}</span>
                {row.description && (
                  <p className="text-xs text-rally-subtle">{row.description}</p>
                )}
              </td>
              <td className="px-4 py-3 font-mono tabular-nums">{formatMoney(row.price_cents)}</td>
              <td className="px-4 py-3">{PERIOD_LABEL[row.billing_period]}</td>
              <td className="px-4 py-3 font-mono tabular-nums">
                {formatMoney(row.overage_rate_cents)}
              </td>
              <td className="px-4 py-3">
                <div className="flex justify-end gap-2">
                  <Button variant="secondary" size="sm" onClick={() => onEdit(row)}>
                    Edit
                  </Button>
                  <Button variant="danger" size="sm" onClick={() => onArchive(row)}>
                    Archive
                  </Button>
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
      title={sessionType ? `Edit ${sessionType.name}` : "New session type"}
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
            <DialogError message="Could not save this session type. Check the values and try again." />
          )}
          {sessionType && (
            <p className="rounded-md bg-status-amber-50 px-3 py-2 text-xs text-status-amber-800">
              Enrollments resolve their price from this plan, so a price change also
              applies to students already enrolled on it.
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
            <FormField label="Billing period" htmlFor="st-period" required>
              <select
                id="st-period"
                value={form.billing_period}
                onChange={(event) =>
                  set("billing_period", event.target.value as SessionTypeBillingPeriod)
                }
                className="h-10 w-full rounded-md border border-rally-line px-3 text-sm outline-none focus:border-blue-500"
              >
                <option value="monthly">Monthly</option>
                <option value="per_session">Per session</option>
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
