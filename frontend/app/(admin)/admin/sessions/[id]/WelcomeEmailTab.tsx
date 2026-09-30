"use client";

/**
 * Class page › Welcome email tab.
 *
 * The seven onboarding facts the enrollment welcome email reads. Each row is
 * either this class's own value (with Reset) or, when blank, the academy
 * default in grey (with Override). One Save PATCHes only the pack fields that
 * changed; the schedule, coach, seats and price are never sent from here.
 */

import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import {
  getAdminAcademy,
  getSelfServicePolicy,
  getSessionWelcomeEmailPreview,
  updateAdminSession,
  type AdminSessionList,
  type AdminSessionView,
} from "@/lib/api/admin";
import { queryKeys } from "@/lib/query/keys";

import { Button } from "@/components/ds/button";
import { Card } from "@/components/ds/card";
import { ErrorNotice } from "@/components/ds/error-notice";
import { LaneHeader } from "@/components/ds/lane";
import { Modal } from "@/components/ds/modal";
import { TableSkeleton } from "@/components/ds/skeleton";

import {
  PACK_ROWS,
  buildPackPatch,
  displayText,
  packDefaults,
  resolveRow,
  storedText,
  type PackDefaults,
  type PackField,
  type PackRowSpec,
} from "./welcome-email-model";

type Drafts = Partial<Record<PackField, string>>;

const INPUT_CLASS =
  "w-full rounded-md border border-rally-line bg-white px-3 py-2 text-sm text-rally-ink";

export function WelcomeEmailTab({ session }: { session: AdminSessionView }) {
  const queryClient = useQueryClient();
  const sessionId = session.session_id;
  const [drafts, setDrafts] = useState<Drafts>({});
  const [editing, setEditing] = useState<ReadonlySet<PackField>>(new Set());
  const [previewOpen, setPreviewOpen] = useState(false);

  const academyQuery = useQuery({
    queryKey: queryKeys.admin.academy(),
    queryFn: getAdminAcademy,
  });
  const policyQuery = useQuery({
    queryKey: queryKeys.admin.selfServicePolicy(),
    queryFn: getSelfServicePolicy,
  });
  const defaults = packDefaults(
    academyQuery.data,
    policyQuery.data?.welcome_email_absence_policy_default,
  );

  const patch = buildPackPatch(session, drafts);
  const dirty = Object.keys(patch).length > 0;

  const save = useMutation({
    mutationFn: () => updateAdminSession(sessionId, patch),
    onSuccess: (saved) => {
      setDrafts({});
      setEditing(new Set());
      queryClient.setQueryData(queryKeys.admin.sessionDetail(sessionId), saved);
      queryClient.setQueryData<AdminSessionList | undefined>(
        queryKeys.admin.sessions("upcoming"),
        (current) =>
          current
            ? {
                sessions: current.sessions.map((row) =>
                  row.session_id === saved.session_id ? saved : row,
                ),
              }
            : current,
      );
      void queryClient.invalidateQueries({ queryKey: queryKeys.admin.sessionDetail(sessionId) });
      void queryClient.invalidateQueries({ queryKey: queryKeys.admin.sessions("upcoming") });
      void queryClient.invalidateQueries({ queryKey: queryKeys.admin.sessionWelcomePreview(sessionId) });
    },
  });

  function setDraft(field: PackField, value: string) {
    setDrafts((current) => ({ ...current, [field]: value }));
  }
  function startEditing(field: PackField, initial: string) {
    setDraft(field, initial);
    setEditing((current) => new Set(current).add(field));
  }
  function stopEditing(field: PackField) {
    setEditing((current) => {
      const next = new Set(current);
      next.delete(field);
      return next;
    });
  }
  function cancelEditing(field: PackField) {
    stopEditing(field);
    setDrafts((current) => {
      const next = { ...current };
      delete next[field];
      return next;
    });
  }
  function reset(field: PackField) {
    stopEditing(field);
    setDraft(field, "");
  }
  function discardAll() {
    setDrafts({});
    setEditing(new Set());
    save.reset();
  }

  const loading = academyQuery.isLoading || policyQuery.isLoading;

  return (
    <Card p={20} className="min-w-0" data-testid="session-welcome-email">
      <LaneHeader
        index="01"
        title="Welcome email"
        action={
          <Button
            variant="secondary"
            size="sm"
            data-testid="welcome-email-preview-open"
            onClick={() => setPreviewOpen(true)}
          >
            Preview email
          </Button>
        }
      />
      <p className="mb-4 text-sm text-rally-muted" data-testid="welcome-email-helper">
        What new families get when they join this class. Grey lines use your academy defaults from
        Settings and update when you change them there.
      </p>
      {loading ? (
        <TableSkeleton />
      ) : (
        <WelcomeEmailRows
          session={session}
          defaults={defaults}
          drafts={drafts}
          editing={editing}
          onDraft={setDraft}
          onOverride={startEditing}
          onCancelEdit={cancelEditing}
          onReset={reset}
        />
      )}
      {(academyQuery.isError || policyQuery.isError) && (
        <ErrorNotice
          className="mt-3"
          message="Could not load your academy defaults. Grey lines may be missing."
          onRetry={() => {
            void academyQuery.refetch();
            void policyQuery.refetch();
          }}
        />
      )}
      {save.isError && (
        <p role="alert" data-testid="welcome-email-error" className="mt-3 text-sm text-red-800">
          {save.error instanceof Error && save.error.message.trim()
            ? `Could not save: ${save.error.message}`
            : "Could not save the welcome email."}
        </p>
      )}
      <div className="mt-5 flex flex-wrap items-center gap-2">
        <Button
          variant="primary"
          size="sm"
          data-testid="welcome-email-save"
          disabled={!dirty || save.isPending}
          onClick={() => save.mutate()}
        >
          {save.isPending ? "Saving…" : "Save"}
        </Button>
        {dirty && (
          <Button variant="ghost" size="sm" data-testid="welcome-email-discard" onClick={discardAll}>
            Discard changes
          </Button>
        )}
        <span className="text-xs text-rally-muted">
          Saving here does not touch the schedule or price.
        </span>
      </div>

      <WelcomeEmailPreviewDialog
        sessionId={sessionId}
        open={previewOpen}
        hasUnsavedChanges={dirty}
        onClose={() => setPreviewOpen(false)}
      />
    </Card>
  );
}

/** The seven rows. Presentational: all state lives in the tab above. */
export function WelcomeEmailRows({
  session,
  defaults,
  drafts,
  editing,
  onDraft,
  onOverride,
  onCancelEdit,
  onReset,
}: {
  session: AdminSessionView;
  defaults: PackDefaults;
  drafts: Drafts;
  editing: ReadonlySet<PackField>;
  onDraft: (field: PackField, value: string) => void;
  onOverride: (field: PackField, initial: string) => void;
  onCancelEdit: (field: PackField) => void;
  onReset: (field: PackField) => void;
}) {
  return (
    <dl className="divide-y divide-rally-line">
      {PACK_ROWS.map((spec) => {
        const own = drafts[spec.field] ?? storedText(session, spec.field);
        const state = resolveRow(spec, own, defaults);
        const isEditing = editing.has(spec.field);
        const testId = `welcome-row-${spec.field}`;
        return (
          <div
            key={spec.field}
            data-testid={testId}
            data-state={isEditing ? "editing" : state.kind}
            className="grid gap-2 py-3 sm:grid-cols-[200px_minmax(0,1fr)_auto] sm:items-start"
          >
            <dt className="text-sm font-medium text-rally-muted">{spec.label}</dt>
            <dd className="min-w-0 text-sm">
              {isEditing ? (
                <RowInput
                  spec={spec}
                  value={drafts[spec.field] ?? ""}
                  onChange={(value) => onDraft(spec.field, value)}
                />
              ) : state.kind === "own" ? (
                <span className="whitespace-pre-line text-rally-ink">
                  {displayText(spec, state.text)}{" "}
                  <span
                    data-testid={`${testId}-tag`}
                    className="ml-1 rounded-full border border-rally-line bg-rally-paper px-2 py-0.5 text-xs font-medium text-rally-ink"
                  >
                    This class
                  </span>
                </span>
              ) : state.kind === "default" ? (
                <span className="whitespace-pre-line text-rally-muted">
                  {displayText(spec, state.text)}{" "}
                  <span data-testid={`${testId}-tag`}>(academy default)</span>
                </span>
              ) : (
                <span className="text-rally-subtle">Not set</span>
              )}
            </dd>
            <div className="flex flex-wrap gap-2 sm:justify-end">
              {isEditing ? (
                <Button
                  variant="ghost"
                  size="sm"
                  data-testid={`${testId}-cancel`}
                  onClick={() => onCancelEdit(spec.field)}
                >
                  Cancel
                </Button>
              ) : state.kind === "own" ? (
                <>
                  <Button
                    variant="secondary"
                    size="sm"
                    data-testid={`${testId}-edit`}
                    aria-label={`Edit ${spec.label}`}
                    onClick={() => onOverride(spec.field, state.text)}
                  >
                    Edit
                  </Button>
                  <Button
                    variant="ghost"
                    size="sm"
                    data-testid={`${testId}-reset`}
                    aria-label={`Reset ${spec.label}`}
                    onClick={() => onReset(spec.field)}
                  >
                    Reset
                  </Button>
                </>
              ) : (
                <Button
                  variant="secondary"
                  size="sm"
                  data-testid={`${testId}-override`}
                  aria-label={`${state.kind === "default" ? "Override" : "Set"} ${spec.label}`}
                  onClick={() =>
                    onOverride(spec.field, state.kind === "default" ? state.text : "")
                  }
                >
                  {state.kind === "default" ? "Override" : "Set"}
                </Button>
              )}
            </div>
          </div>
        );
      })}
    </dl>
  );
}

function RowInput({
  spec,
  value,
  onChange,
}: {
  spec: PackRowSpec;
  value: string;
  onChange: (value: string) => void;
}) {
  const id = `welcome-input-${spec.field}`;
  if (spec.kind === "minutes") {
    return (
      <input
        id={id}
        data-testid={id}
        aria-label={spec.label}
        type="number"
        min={1}
        max={120}
        inputMode="numeric"
        className={`${INPUT_CLASS} max-w-[8rem]`}
        value={value}
        onChange={(event) => onChange(event.target.value)}
      />
    );
  }
  if (spec.kind === "multiline") {
    return (
      <textarea
        id={id}
        data-testid={id}
        aria-label={spec.label}
        rows={2}
        maxLength={spec.field === "absence_policy" ? 1000 : 500}
        className={INPUT_CLASS}
        value={value}
        onChange={(event) => onChange(event.target.value)}
      />
    );
  }
  return (
    <input
      id={id}
      data-testid={id}
      aria-label={spec.label}
      type="url"
      placeholder="https://chat.whatsapp.com/…"
      maxLength={2048}
      className={INPUT_CLASS}
      value={value}
      onChange={(event) => onChange(event.target.value)}
    />
  );
}

function WelcomeEmailPreviewDialog({
  sessionId,
  open,
  hasUnsavedChanges,
  onClose,
}: {
  sessionId: string;
  open: boolean;
  hasUnsavedChanges: boolean;
  onClose: () => void;
}) {
  const previewQuery = useQuery({
    queryKey: queryKeys.admin.sessionWelcomePreview(sessionId),
    queryFn: () => getSessionWelcomeEmailPreview(sessionId),
    enabled: open,
    // A preview is a render of saved data: always show the latest.
    staleTime: 0,
  });
  return (
    <Modal
      open={open}
      onClose={onClose}
      size="lg"
      title="Welcome email preview"
      footer={
        <Button variant="secondary" size="sm" onClick={onClose}>
          Close
        </Button>
      }
    >
      <p className="mb-3 text-sm text-rally-muted">
        Exactly what a new family gets, using a sample student name. Nothing is sent.
        {hasUnsavedChanges ? " This shows the saved version, without your unsaved changes." : ""}
      </p>
      {previewQuery.isLoading ? (
        <TableSkeleton />
      ) : previewQuery.isError || !previewQuery.data ? (
        <ErrorNotice
          message="Could not load the preview."
          onRetry={() => void previewQuery.refetch()}
          retrying={previewQuery.isFetching}
        />
      ) : (
        <WelcomeEmailPreviewFrame subject={previewQuery.data.subject} html={previewQuery.data.html} />
      )}
    </Modal>
  );
}

/** The rendered email. No `allow-scripts`: the email is markup only; popups let links be checked. */
export function WelcomeEmailPreviewFrame({ subject, html }: { subject: string; html: string }) {
  return (
    <>
      <p className="mb-2 text-sm font-semibold text-rally-ink" data-testid="welcome-email-preview-subject">
        {subject}
      </p>
      <iframe
        title="Welcome email preview"
        data-testid="welcome-email-preview-frame"
        sandbox="allow-popups allow-popups-to-escape-sandbox"
        srcDoc={html}
        className="h-[420px] w-full rounded-md border border-rally-line bg-white"
      />
    </>
  );
}
