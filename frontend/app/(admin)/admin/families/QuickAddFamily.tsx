"use client";

/**
 * Quick add (L12): a walk-in or phone sign-up in one form, built entirely
 * from existing endpoints so every rule stays on the server:
 *
 * 1. the CSV import's preview with a one-row file: the same validation and
 *    People CRM duplicate finder (an existing family gets the child added);
 * 2. the import's commit, which mints the child;
 * 3. optionally the admin roster add (`POST /admin/enrollments`), which
 *    holds the seat and drives billing exactly as the roster page does;
 * 4. optionally the Billing Setup login invite.
 *
 * A failure after step 2 leaves the family saved; the result says which step
 * failed so staff finish it from the family page instead of re-adding.
 */

import { useState } from "react";
import type { Route } from "next";
import Link from "next/link";
import { useMutation, useQuery } from "@tanstack/react-query";

import {
  IMPORT_COLUMNS,
  commitFamilyImport,
  previewFamilyImport,
  type ImportBatch,
  type ImportRow,
} from "@/lib/api/admin-family-import";
import { createEnrollment, inviteBillingSetupParent, listAdminSessions } from "@/lib/api/admin";
import { quoteCell } from "@/lib/admin/import-column-mapping";
import { queryKeys } from "@/lib/query/keys";
import { Button } from "@/components/ds/button";
import { Card } from "@/components/ds/card";
import { Overline } from "@/components/ds/typography";

export interface QuickAddForm {
  parent_name: string;
  parent_email: string;
  parent_phone: string;
  student_name: string;
  student_date_of_birth: string;
}

const EMPTY: QuickAddForm = {
  parent_name: "",
  parent_email: "",
  parent_phone: "",
  student_name: "",
  student_date_of_birth: "",
};

/** The one-row import file this form stands for, in the import's column order. */
export function quickAddCsv(form: QuickAddForm): string {
  const cells = IMPORT_COLUMNS.map((column) => quoteCell(form[column].trim()));
  return `${IMPORT_COLUMNS.join(",")}\r\n${cells.join(",")}\r\n`;
}

export type StepResult = {
  family: ImportRow;
  enrolled: boolean | null;
  invited: boolean | null;
  failure?: string;
  /** The commit created no child (it was already on file): nothing else ran. */
  existed?: boolean;
};

const INPUT =
  "rounded-md border border-neutral-200 px-2 py-1.5 text-sm dark:border-neutral-700 dark:bg-neutral-900";

function message(error: unknown, fallback: string): string {
  return error instanceof Error && error.message ? error.message : fallback;
}

/**
 * Steps 2-4 of quick add. Stops after the commit when it created no child, so
 * the form never claims "Added" or skips the enrollment silently.
 */
export async function runQuickAdd({
  batchId,
  sessionId,
  invite,
}: {
  batchId: string;
  sessionId: string;
  invite: boolean;
}): Promise<StepResult> {
  const committed = await commitFamilyImport(batchId);
  const family = committed.rows[0];
  if (!family) throw new Error("The import returned no row; check the Families list.");
  const out: StepResult = { family, enrolled: null, invited: null };
  const parentId = family.family_id;
  if (family.status !== "create" || !family.student_id || !parentId) {
    return { ...out, existed: true };
  }
  if (sessionId) {
    try {
      await createEnrollment({
        session_id: sessionId,
        student_id: family.student_id,
        parent_id: parentId,
        full_name: family.student_name,
      });
      out.enrolled = true;
    } catch (error) {
      out.enrolled = false;
      out.failure = message(error, "The class enrollment failed.");
      return out;
    }
  }
  if (invite) {
    try {
      const sent = await inviteBillingSetupParent(parentId);
      out.invited = sent.ok;
      if (!sent.ok) out.failure = sent.failed_reason ?? "The login invite was not sent.";
    } catch (error) {
      out.invited = false;
      out.failure = message(error, "The login invite was not sent.");
    }
  }
  return out;
}

export function QuickAddFamily({ onAdded }: { onAdded: () => void }) {
  const [open, setOpen] = useState(false);
  const [form, setForm] = useState<QuickAddForm>(EMPTY);
  const [sessionId, setSessionId] = useState("");
  const [invite, setInvite] = useState(true);
  const [checked, setChecked] = useState<ImportBatch | null>(null);
  const [result, setResult] = useState<StepResult | null>(null);

  const sessionsQuery = useQuery({
    queryKey: queryKeys.admin.sessions("upcoming"),
    queryFn: () => listAdminSessions(undefined, { window: "upcoming" }),
    enabled: open,
  });

  const check = useMutation({
    mutationFn: () => previewFamilyImport({ csv: quickAddCsv(form), filename: "quick-add" }),
    onSuccess: (batch) => {
      setResult(null);
      setChecked(batch);
    },
  });

  const add = useMutation({
    mutationFn: () =>
      runQuickAdd({
        batchId: checked!.import_batch_id,
        sessionId,
        invite: invite && Boolean(form.parent_email.trim()),
      }),
    onSuccess: (data) => {
      setChecked(null);
      setResult(data);
      setForm(EMPTY);
      setSessionId("");
      onAdded();
    },
  });

  const set = (field: keyof QuickAddForm) => (value: string) => {
    setChecked(null);
    setForm((prev) => ({ ...prev, [field]: value }));
  };
  const row = checked?.rows[0];
  const ready =
    form.parent_name.trim() &&
    form.student_name.trim() &&
    (form.parent_email.trim() || form.parent_phone.trim());

  if (!open) {
    return (
      <div className="flex flex-wrap items-center gap-3">
        <Button size="sm" onClick={() => setOpen(true)} data-testid="quick-add-open">
          New family
        </Button>
        {result && <QuickAddResult result={result} />}
      </div>
    );
  }

  const field = (label: string, key: keyof QuickAddForm, type = "text", hint?: string) => (
    <label className="grid gap-1 text-sm">
      {label}
      <input
        type={type}
        value={form[key]}
        maxLength={key === "parent_email" ? 254 : 120}
        placeholder={hint}
        onChange={(e) => set(key)(e.target.value)}
        className={INPUT}
        data-testid={`quick-add-${key}`}
      />
    </label>
  );

  return (
    <Card p={24} data-testid="quick-add-card">
      <Overline>New family</Overline>
      <p className="mt-2 text-sm text-rally-muted">
        Add a parent and child, and optionally enroll the child in a class.
        We check for an existing family first; a match gets the child added to
        it instead.
      </p>
      <div className="mt-4 grid gap-3 sm:grid-cols-2">
        {field("Parent name", "parent_name")}
        {field("Parent email", "parent_email", "email")}
        {field("Parent phone", "parent_phone", "tel")}
        {field("Child name", "student_name")}
        {field("Child date of birth (optional)", "student_date_of_birth", "date")}
        <label className="grid gap-1 text-sm">
          Class (optional)
          <select
            value={sessionId}
            onChange={(e) => setSessionId(e.target.value)}
            className={INPUT}
            data-testid="quick-add-session"
          >
            <option value="">Do not enroll yet</option>
            {(sessionsQuery.data?.sessions ?? []).map((s) => (
              <option key={s.session_id} value={s.session_id}>
                {s.title}
              </option>
            ))}
          </select>
        </label>
      </div>
      <label className="mt-3 flex items-center gap-2 text-sm">
        <input
          type="checkbox"
          checked={invite}
          onChange={(e) => setInvite(e.target.checked)}
          data-testid="quick-add-invite"
        />
        Email the parent a login invite (needs an email)
      </label>
      <div className="mt-4 flex flex-wrap gap-2">
        <Button
          variant="secondary"
          disabled={!ready || check.isPending}
          onClick={() => check.mutate()}
          data-testid="quick-add-check"
        >
          {check.isPending ? "Checking..." : "Check details"}
        </Button>
        <Button variant="secondary" onClick={() => setOpen(false)}>
          Close
        </Button>
      </div>
      {(check.error || add.error) && (
        <p className="mt-3 text-sm text-red-700" role="alert">
          {message(check.error ?? add.error, "Could not add this family.")}
        </p>
      )}
      {row && (
        <div className="mt-4 text-sm" data-testid="quick-add-check-result">
          {row.errors.length > 0 && (
            <ul className="space-y-1 text-red-700" role="alert">
              {row.errors.map((issue) => (
                <li key={`${issue.field}-${issue.message}`}>{issue.message}</li>
              ))}
            </ul>
          )}
          {row.warnings.map((warning) => (
            <p key={warning} className="text-rally-muted">
              {warning}
            </p>
          ))}
          {row.status === "create" && (
            <>
              <p className="font-medium text-rally-ink">
                {row.family_action === "existing"
                  ? `${row.student_name} will be added to the existing ${row.family_name ?? "family"}.`
                  : `A new family for ${row.parent_name} with ${row.student_name}.`}
              </p>
              <Button
                className="mt-3"
                disabled={add.isPending}
                onClick={() => add.mutate()}
                data-testid="quick-add-save"
              >
                {add.isPending ? "Adding..." : sessionId ? "Add and enroll" : "Add family"}
              </Button>
            </>
          )}
          {row.status === "skip" && row.family_link && (
            <Link className="mt-2 inline-block text-rally-cobalt underline" href={row.family_link as Route}>
              Open the family to enroll this child
            </Link>
          )}
        </div>
      )}
      {result && <QuickAddResult result={result} />}
    </Card>
  );
}

export function QuickAddResult({ result }: { result: StepResult }) {
  const { family } = result;
  const familyHref = family.family_link ?? (family.family_id ? `/admin/families/${encodeURIComponent(family.family_id)}` : null);
  if (result.existed) {
    return (
      <div className="mt-3 text-sm" role="status" data-testid="quick-add-result">
        <p className="text-rally-ink">
          {family.student_name} already existed, so nothing was added.{" "}
          {familyHref && (
            <Link className="text-rally-cobalt underline" href={familyHref as Route}>
              Open the family to enroll
            </Link>
          )}
        </p>
      </div>
    );
  }
  return (
    <div className="mt-3 text-sm" role="status" data-testid="quick-add-result">
      <p className="text-rally-ink">
        Added {family.student_name}
        {result.enrolled ? " and enrolled them" : ""}
        {result.invited ? "; login invite sent" : ""}.{" "}
        {family.family_id && (
          <Link
            className="text-rally-cobalt underline"
            href={`/admin/families/${encodeURIComponent(family.family_id)}` as Route}
          >
            Open the family
          </Link>
        )}
      </p>
      {result.failure && (
        <p className="mt-1 text-red-700" role="alert">
          Saved the family, but: {result.failure} Finish this from the family page.
        </p>
      )}
    </div>
  );
}
