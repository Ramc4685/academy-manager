"use client";

import Link from "next/link";
import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import {
  assignAdminWaiverTemplate,
  createAdminWaiverTemplate,
  listAdminWaivers,
  listAdminWaiverTemplates,
  publishAdminWaiverTemplate,
  type AdminCurrentWaiverView,
  type AdminWaiverAssignRequest,
  type AdminWaiverProgram,
  type AdminWaiverTemplateManagementView,
  type AdminWaiverStatus,
  type AdminWaiverStudentRow,
  type AdminWaiverSummary,
} from "@/lib/api/admin";
import { queryKeys } from "@/lib/query/keys";
import { Avatar, BigNum, Card, Chip, LaneHeader, Overline } from "@/components/ds";
import { requiredForLabel } from "@/lib/admin/waiver-assignment";

/**
 * Waiver template list/editor/publish UI (issue #613 area), reused from the
 * standalone `/admin/waivers` page.
 *
 * Settings overhaul Phase 3 PR 10: this used to be the whole
 * `AdminWaiversPage` component. It now lives here so both the settings ->
 * Family policies "Registration & waivers" card and `/admin/waivers`'s
 * sub-routes (`[waiverId]`, `signatures/[signatureId]`) can reach the same
 * template-management UI without duplicating the waiver logic. The
 * `/admin/waivers` index route itself now redirects here (see
 * `app/(admin)/admin/waivers/page.tsx`).
 */
export function WaiversManagement() {
  const queryClient = useQueryClient();
  const waiversQuery = useQuery({
    queryKey: queryKeys.admin.waivers(),
    queryFn: () => listAdminWaivers(),
    retry: false,
  });
  const templatesQuery = useQuery({
    queryKey: queryKeys.admin.waiverTemplates(),
    queryFn: () => listAdminWaiverTemplates(),
    retry: false,
  });

  const refreshTemplates = () => {
    void queryClient.invalidateQueries({ queryKey: queryKeys.admin.waiverTemplates() });
    void queryClient.invalidateQueries({ queryKey: queryKeys.admin.waivers() });
  };

  const createMutation = useMutation({
    mutationFn: createAdminWaiverTemplate,
    onSuccess: refreshTemplates,
  });
  const publishMutation = useMutation({
    mutationFn: publishAdminWaiverTemplate,
    onSuccess: refreshTemplates,
  });
  const assignMutation = useMutation({
    mutationFn: (vars: { templateId: string; payload: AdminWaiverAssignRequest }) =>
      assignAdminWaiverTemplate(vars.templateId, vars.payload),
    onSuccess: refreshTemplates,
  });

  if (waiversQuery.isError) {
    return (
      <section data-testid="admin-waivers" className="space-y-5">
        <Card p={16} style={{ borderColor: "#fecaca", background: "#fef2f2" }}>
          <div role="alert" data-testid="admin-waivers-error" className="text-sm text-red-800">
            Could not load waivers.
          </div>
        </Card>
      </section>
    );
  }

  if (waiversQuery.isPending) {
    return (
      <section data-testid="admin-waivers" className="space-y-6">
        <SummarySkeleton />
        <Card p={20}>
          <div className="h-5 w-44 rounded bg-neutral-100" />
          <div className="mt-5 space-y-3">
            <div className="h-4 w-full rounded bg-neutral-100" />
            <div className="h-4 w-5/6 rounded bg-neutral-100" />
            <div className="h-4 w-2/3 rounded bg-neutral-100" />
          </div>
        </Card>
      </section>
    );
  }

  const summary = waiversQuery.data.summary;
  const currentWaiver = waiversQuery.data.current_waiver ?? null;
  const waivers = waiversQuery.data.waivers ?? [];

  return (
    <section data-testid="admin-waivers" className="space-y-6">
      <SummaryCards summary={summary} />

      <LaneHeader index="01" title="Current waiver" />
      <CurrentWaiverCard waiver={currentWaiver} summary={summary} />

      <LaneHeader index="02" title="Template management" />
      <TemplateManagementPanel
        templates={templatesQuery.data?.templates ?? []}
        programs={templatesQuery.data?.programs ?? []}
        loading={templatesQuery.isPending}
        error={templatesQuery.isError}
        createPending={createMutation.isPending}
        publishPending={publishMutation.isPending}
        assignPending={assignMutation.isPending}
        assignFailed={assignMutation.isError}
        onCreate={(payload) => createMutation.mutate(payload)}
        onPublish={(templateId) => publishMutation.mutate(templateId)}
        onAssign={(templateId, payload, onDone) =>
          assignMutation.mutate({ templateId, payload }, { onSuccess: onDone })
        }
      />

      <LaneHeader index="03" title="Per-student status" />
      <Card p={0}>
        {waivers.length === 0 ? (
          <p className="p-5 text-sm text-rally-subtle" data-testid="admin-waivers-empty">
            No waiver rows returned.
          </p>
        ) : (
          <WaiversTable waivers={waivers} />
        )}
      </Card>
    </section>
  );
}

function TemplateManagementPanel({
  templates,
  programs,
  loading,
  error,
  createPending,
  publishPending,
  assignPending,
  assignFailed,
  onCreate,
  onPublish,
  onAssign,
}: {
  templates: AdminWaiverTemplateManagementView[];
  programs: AdminWaiverProgram[];
  loading: boolean;
  error: boolean;
  createPending: boolean;
  publishPending: boolean;
  assignPending: boolean;
  assignFailed: boolean;
  onCreate: (payload: {
    title: string;
    body: string;
    based_on_waiver_template_id?: string | null;
  }) => void;
  onPublish: (templateId: string) => void;
  onAssign: (templateId: string, payload: AdminWaiverAssignRequest, onDone: () => void) => void;
}) {
  const [title, setTitle] = useState("");
  const [body, setBody] = useState("");
  const [basedOn, setBasedOn] = useState<AdminWaiverTemplateManagementView | null>(null);
  const [assigningId, setAssigningId] = useState<string | null>(null);
  const [formError, setFormError] = useState<string | null>(null);

  const startNewVersion = (template: AdminWaiverTemplateManagementView) => {
    setBasedOn(template);
    setTitle(template.title);
    setBody(template.body);
    setFormError(null);
  };
  const resetForm = () => {
    setBasedOn(null);
    setTitle("");
    setBody("");
    setFormError(null);
  };

  const submit = () => {
    const cleanTitle = title.trim();
    const cleanBody = body.trim();
    if (!cleanTitle || !cleanBody) {
      setFormError("Title and waiver body are required.");
      return;
    }
    setFormError(null);
    onCreate({
      title: cleanTitle,
      body: cleanBody,
      ...(basedOn ? { based_on_waiver_template_id: basedOn.waiver_template_id } : {}),
    });
    resetForm();
  };

  const current = templates.filter((template) => template.status === "active" || template.status === "draft");
  const older = templates.filter((template) => template.status !== "active" && template.status !== "draft");

  return (
    <div className="grid gap-4">
      <Card p={20} data-testid="admin-waiver-form">
        <Overline>{basedOn ? `New version of ${basedOn.title}` : "New waiver"}</Overline>
        <p className="mt-2 text-[13px] text-rally-muted">
          {basedOn
            ? "Publishing replaces the live version of this waiver. Your other waivers stay live."
            : "Adds a separate waiver. It does not replace the ones you already have."}
        </p>
        <div className="mt-4 space-y-3">
          <label className="block text-sm font-semibold text-rally-ink">
            Template title
            <input
              value={title}
              onChange={(event) => setTitle(event.target.value)}
              className="mt-2 min-h-touch w-full rounded-md border border-neutral-200 px-3 py-2 text-sm outline-none focus:border-rally-cobalt"
              placeholder="Liability and media release"
            />
          </label>
          <label className="block text-sm font-semibold text-rally-ink">
            Waiver body
            <textarea
              value={body}
              onChange={(event) => setBody(event.target.value)}
              className="mt-2 min-h-[160px] w-full rounded-md border border-neutral-200 px-3 py-2 text-sm leading-6 outline-none focus:border-rally-cobalt"
              placeholder="Paste the exact waiver text parents must sign."
            />
          </label>
          {formError && <p role="alert" className="text-sm text-red-700">{formError}</p>}
          <div className="flex flex-wrap gap-2">
            <button
              type="button"
              onClick={submit}
              disabled={createPending}
              className="inline-flex min-h-touch items-center rounded-md bg-rally-ink px-3 py-2 text-sm font-semibold text-white disabled:cursor-not-allowed disabled:opacity-50"
            >
              {createPending ? "Saving..." : "Create draft"}
            </button>
            {basedOn && (
              <button
                type="button"
                onClick={resetForm}
                data-testid="admin-waiver-form-cancel"
                className="inline-flex min-h-touch items-center rounded-md border border-neutral-200 px-3 py-2 text-sm font-semibold text-rally-ink"
              >
                Cancel
              </button>
            )}
          </div>
        </div>
      </Card>

      <Card p={0}>
        {loading ? (
          <p className="p-5 text-sm text-rally-subtle">Loading templates...</p>
        ) : error ? (
          <p role="alert" className="p-5 text-sm text-red-700">Could not load waiver templates.</p>
        ) : templates.length === 0 ? (
          <p className="p-5 text-sm text-rally-subtle" data-testid="admin-waiver-templates-empty">
            No waiver templates created yet.
          </p>
        ) : (
          <div data-testid="admin-waiver-list">
            <div className="border-b border-neutral-200 bg-neutral-50 px-5 py-3">
              <Overline>Waivers · who signs what</Overline>
            </div>
            <ul className="divide-y divide-neutral-100">
              {current.map((template) => (
                <li
                  key={template.waiver_template_id}
                  data-testid={`admin-waiver-template-row-${template.waiver_template_id}`}
                  className="px-5 py-4"
                >
                  <div className="flex flex-wrap items-start justify-between gap-3">
                    <div className="min-w-0">
                      <div className="font-semibold text-rally-base">
                        {template.title}
                        <span className="ml-2 font-mono text-[11px] font-normal text-rally-subtle">
                          {template.version ? `v${template.version}` : "Draft"}
                        </span>
                      </div>
                      <div
                        className="mt-1 text-[12px] text-rally-muted"
                        data-testid={`admin-waiver-required-for-${template.waiver_template_id}`}
                      >
                        {template.status === "draft"
                          ? "Publish to assign"
                          : `Required for: ${requiredForLabel(template, programs)}`}
                      </div>
                    </div>
                    <Chip variant={chipForTemplate(template)} label={statusLabel(template)} />
                  </div>
                  <div className="mt-3 flex flex-wrap gap-2">
                    <Link
                      href={`/admin/waivers/${encodeURIComponent(template.waiver_template_id)}`}
                      className="inline-flex min-h-touch items-center rounded-md border border-neutral-200 px-3 py-2 text-sm font-semibold text-rally-ink"
                    >
                      Open
                    </Link>
                    {template.status === "draft" && (
                      <button
                        type="button"
                        onClick={() => onPublish(template.waiver_template_id)}
                        disabled={publishPending}
                        data-testid={`admin-waiver-publish-${template.waiver_template_id}`}
                        className="inline-flex min-h-touch items-center rounded-md bg-rally-cobalt px-3 py-2 text-sm font-semibold text-white disabled:cursor-not-allowed disabled:opacity-50"
                      >
                        Publish
                      </button>
                    )}
                    {template.status === "active" && (
                      <>
                        <button
                          type="button"
                          onClick={() =>
                            setAssigningId(
                              assigningId === template.waiver_template_id
                                ? null
                                : template.waiver_template_id,
                            )
                          }
                          aria-expanded={assigningId === template.waiver_template_id}
                          data-testid={`admin-waiver-assign-button-${template.waiver_template_id}`}
                          className="inline-flex min-h-touch items-center rounded-md bg-rally-ink px-3 py-2 text-sm font-semibold text-white"
                        >
                          Assign
                        </button>
                        <button
                          type="button"
                          onClick={() => startNewVersion(template)}
                          data-testid={`admin-waiver-new-version-${template.waiver_template_id}`}
                          className="inline-flex min-h-touch items-center rounded-md border border-neutral-200 px-3 py-2 text-sm font-semibold text-rally-ink"
                        >
                          New version
                        </button>
                      </>
                    )}
                  </div>
                  {template.status === "active" && assigningId === template.waiver_template_id && (
                    <AssignPanel
                      template={template}
                      programs={programs}
                      pending={assignPending}
                      failed={assignFailed}
                      onCancel={() => setAssigningId(null)}
                      onSave={(payload) =>
                        onAssign(template.waiver_template_id, payload, () => setAssigningId(null))
                      }
                    />
                  )}
                </li>
              ))}
            </ul>
            {older.length > 0 && (
              <details className="border-t border-neutral-100 px-5 py-3" data-testid="admin-waiver-older">
                <summary className="cursor-pointer text-[12px] font-semibold text-rally-muted">
                  Older versions ({older.length})
                </summary>
                <ul className="mt-2 space-y-1">
                  {older.map((template) => (
                    <li
                      key={template.waiver_template_id}
                      data-testid={`admin-waiver-template-row-${template.waiver_template_id}`}
                      className="flex items-center justify-between gap-3 text-[12px] text-rally-muted"
                    >
                      <span>
                        {template.title}
                        {template.version ? ` v${template.version}` : ""}
                      </span>
                      <Link
                        href={`/admin/waivers/${encodeURIComponent(template.waiver_template_id)}`}
                        className="font-semibold text-rally-cobalt hover:underline"
                      >
                        Open
                      </Link>
                    </li>
                  ))}
                </ul>
              </details>
            )}
          </div>
        )}
      </Card>
    </div>
  );
}

type AssignChoice = "none" | "all" | "programs";

function AssignPanel({
  template,
  programs,
  pending,
  failed,
  onCancel,
  onSave,
}: {
  template: AdminWaiverTemplateManagementView;
  programs: AdminWaiverProgram[];
  pending: boolean;
  failed: boolean;
  onCancel: () => void;
  onSave: (payload: AdminWaiverAssignRequest) => void;
}) {
  const id = template.waiver_template_id;
  const initialRequired = template.required ?? template.assigned_to_registration;
  const [choice, setChoice] = useState<AssignChoice>(
    !initialRequired ? "none" : template.scope === "programs" ? "programs" : "all",
  );
  const [selected, setSelected] = useState<string[]>(template.program_ids ?? []);
  const canSave = choice !== "programs" || selected.length > 0;

  const toggle = (programId: string) =>
    setSelected((prev) =>
      prev.includes(programId) ? prev.filter((item) => item !== programId) : [...prev, programId],
    );

  const save = () => {
    if (!canSave) return;
    onSave({
      required: choice !== "none",
      scope: choice === "programs" ? "programs" : "all",
      program_ids: choice === "programs" ? selected : [],
    });
  };

  const radio = (value: AssignChoice, label: string, disabled = false) => (
    <label className="flex min-h-touch items-center gap-2 text-sm text-rally-ink">
      <input
        type="radio"
        name={`assign-${id}`}
        value={value}
        checked={choice === value}
        disabled={disabled}
        onChange={() => setChoice(value)}
        data-testid={`admin-waiver-assign-choice-${id}-${value}`}
      />
      {label}
    </label>
  );

  return (
    <div
      data-testid={`admin-waiver-assign-${id}`}
      className="mt-3 rounded-md border border-neutral-200 bg-neutral-50 p-4"
    >
      <Overline>Who signs this waiver</Overline>
      <div className="mt-2">
        {radio("none", "Not required")}
        {radio("all", "All families")}
        {radio("programs", "Only families in these programs", programs.length === 0)}
      </div>
      {programs.length === 0 && (
        <p className="mt-1 text-[12px] text-rally-subtle">
          No programs yet. Add programs in Public page to assign a waiver to one.
        </p>
      )}
      {choice === "programs" && programs.length > 0 && (
        <div className="mt-2 space-y-1 pl-6" role="group" aria-label="Programs">
          {programs.map((program) => (
            <label
              key={program.program_id}
              className="flex min-h-touch items-center gap-2 text-sm text-rally-ink"
            >
              <input
                type="checkbox"
                checked={selected.includes(program.program_id)}
                onChange={() => toggle(program.program_id)}
                data-testid={`admin-waiver-assign-program-${id}-${program.program_id}`}
              />
              {program.name}
            </label>
          ))}
        </div>
      )}
      <p className="mt-2 text-[12px] text-rally-subtle">
        A family that has not signed is flagged to staff. It never blocks enrollment.
      </p>
      {failed && (
        <p role="alert" className="mt-2 text-sm text-red-700">
          Could not save. Try again.
        </p>
      )}
      <div className="mt-3 flex flex-wrap gap-2">
        <button
          type="button"
          onClick={save}
          disabled={pending || !canSave}
          data-testid={`admin-waiver-assign-save-${id}`}
          className="inline-flex min-h-touch items-center rounded-md bg-rally-ink px-3 py-2 text-sm font-semibold text-white disabled:cursor-not-allowed disabled:opacity-50"
        >
          {pending ? "Saving..." : "Save"}
        </button>
        <button
          type="button"
          onClick={onCancel}
          className="inline-flex min-h-touch items-center rounded-md border border-neutral-200 px-3 py-2 text-sm font-semibold text-rally-ink"
        >
          Cancel
        </button>
      </div>
    </div>
  );
}

function statusLabel(template: AdminWaiverTemplateManagementView): string {
  if (template.status === "active") return "LIVE";
  if (template.status === "draft") return "DRAFT";
  return template.status.toUpperCase();
}

function SummaryCards({ summary }: { summary: AdminWaiverSummary }) {
  return (
    <div className="grid grid-cols-2 gap-4 md:grid-cols-4">
      <Card p={20} accent="#10b981">
        <Overline>Signed current</Overline>
        <BigNum size={32}>{summary.signed_current}</BigNum>
        <p className="mt-1 text-[11px] text-rally-subtle">
          {formatPercent(summary.adoption_rate) ?? "Active waiver on file"}
        </p>
      </Card>
      <Card p={20} accent="#f59e0b">
        <Overline>Pending signature</Overline>
        <BigNum size={32}>{summary.pending_signature}</BigNum>
        <p className="mt-1 text-[11px] text-rally-subtle">Blocks first session</p>
      </Card>
      <Card p={20} accent="#facc15">
        <Overline>Expiring 30d</Overline>
        <BigNum size={32}>{summary.expiring_30d}</BigNum>
        <p className="mt-1 text-[11px] text-rally-subtle">Renewal attention needed</p>
      </Card>
      <Card p={20} accent="var(--rally-subtle-ink)">
        <Overline>Outdated version</Overline>
        <BigNum size={32}>{summary.outdated_version}</BigNum>
        <p className="mt-1 text-[11px] text-rally-subtle">Previous waiver version</p>
      </Card>
    </div>
  );
}

function SummarySkeleton() {
  return (
    <div className="grid grid-cols-2 gap-4 md:grid-cols-4" aria-label="Loading waiver summary">
      {["signed", "pending", "expiring", "outdated"].map((key) => (
        <Card key={key} p={20}>
          <div className="h-3 w-24 rounded bg-neutral-100" />
          <div className="mt-3 h-8 w-14 rounded bg-neutral-100" />
          <div className="mt-3 h-3 w-28 rounded bg-neutral-100" />
        </Card>
      ))}
    </div>
  );
}

function CurrentWaiverCard({
  waiver,
  summary,
}: {
  waiver: AdminCurrentWaiverView | null;
  summary: AdminWaiverSummary;
}) {
  if (!waiver) {
    return (
      <Card p={20}>
        <p className="text-sm text-rally-subtle">
          Current waiver details are not available yet.
        </p>
      </Card>
    );
  }

  const adoption =
    waiver.adoption_rate != null
      ? formatPercent(waiver.adoption_rate)
      : waiver.signed_count != null && waiver.total_count
        ? `${waiver.signed_count} / ${waiver.total_count}`
        : summary.active_students
          ? `${summary.signed_current} / ${summary.active_students}`
          : null;

  return (
    <div className="grid gap-4 lg:grid-cols-[1.35fr_0.65fr]">
      <Card p={24}>
        <div className="flex flex-col gap-5 sm:flex-row sm:items-start">
          <div className="relative flex h-[72px] w-14 shrink-0 flex-col items-center justify-center rounded-md bg-rally-ink px-2 text-center">
            <span className="absolute left-0 right-0 top-2 h-0.5 bg-rally-volt-400" />
            <span className="font-mono text-[9px] font-bold tracking-[0.15em] text-rally-volt-400">WAIVER</span>
            <span className="mt-1 font-display text-[22px] font-bold tracking-[-0.02em] text-white">
              {waiver.version}
            </span>
          </div>
          <div className="min-w-0 flex-1">
            <Overline>Current template</Overline>
            <h2 className="mt-1 font-display text-[22px] font-semibold tracking-[-0.02em] text-rally-ink">
              {waiver.title}
            </h2>
            {waiver.description && (
              <p className="mt-2 max-w-2xl text-[13px] leading-6 text-rally-muted">{waiver.description}</p>
            )}
            <dl className="mt-5 grid gap-4 border-t border-neutral-100 pt-4 sm:grid-cols-3">
              <MetaTerm label="Effective" value={formatDate(waiver.effective_at)} />
              <MetaTerm label="Last edited" value={formatDate(waiver.last_edited_at)} />
              <MetaTerm label="Adoption" value={adoption ?? "Not reported"} />
            </dl>
            <div className="mt-5">
              <Link
                href={`/admin/waivers/${encodeURIComponent(waiver.waiver_id)}`}
                className="inline-flex min-h-touch items-center rounded-md bg-rally-ink px-3 py-2 text-sm font-semibold text-white transition hover:bg-rally-ink/90"
              >
                Open template
              </Link>
            </div>
          </div>
        </div>
      </Card>

      <Card p={20}>
        <Overline>Template status</Overline>
        <div className="mt-4 space-y-3 text-sm">
          <div className="flex items-center justify-between gap-3">
            <span className="text-rally-muted">Current version</span>
            <span className="font-mono text-[12px] font-bold tracking-[0.05em] text-rally-ink">{waiver.version}</span>
          </div>
          <div className="flex items-center justify-between gap-3">
            <span className="text-rally-muted">Pending</span>
            <span className="font-mono text-[12px] font-bold tracking-[0.05em] text-rally-ink">
              {summary.pending_signature}
            </span>
          </div>
          <div className="flex items-center justify-between gap-3">
            <span className="text-rally-muted">Expiring soon</span>
            <span className="font-mono text-[12px] font-bold tracking-[0.05em] text-rally-ink">
              {summary.expiring_30d}
            </span>
          </div>
        </div>
        <div className="mt-5 border-t border-neutral-100 pt-4">
          <p className="text-[12px] leading-5 text-rally-subtle">
            Signed waiver PDF artifacts and share links need backend support before they
            can be opened or exported here.
          </p>
        </div>
      </Card>
    </div>
  );
}

function MetaTerm({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <Overline>{label}</Overline>
      <dd className="mt-1 font-mono text-[11px] font-semibold uppercase tracking-[0.08em] text-rally-ink">{value}</dd>
    </div>
  );
}

function WaiversTable({ waivers }: { waivers: AdminWaiverStudentRow[] }) {
  return (
    <div className="overflow-x-auto">
      <table className="w-full min-w-[900px] text-sm">
        <thead>
          <tr className="border-b border-neutral-200 bg-neutral-50 text-left dark:border-neutral-800">
            <th className="px-5 py-3 font-mono text-[10px] font-bold uppercase tracking-overline text-rally-muted">Student and parent</th>
            <th className="px-3 py-3 font-mono text-[10px] font-bold uppercase tracking-overline text-rally-muted">Version</th>
            <th className="px-3 py-3 font-mono text-[10px] font-bold uppercase tracking-overline text-rally-muted">Signed</th>
            <th className="px-3 py-3 font-mono text-[10px] font-bold uppercase tracking-overline text-rally-muted">Method</th>
            <th className="px-3 py-3 font-mono text-[10px] font-bold uppercase tracking-overline text-rally-muted">Artifact</th>
            <th className="px-5 py-3 font-mono text-[10px] font-bold uppercase tracking-overline text-rally-muted">Status</th>
            <th className="px-5 py-3 font-mono text-[10px] font-bold uppercase tracking-overline text-rally-muted">Detail</th>
          </tr>
        </thead>
        <tbody>
          {waivers.map((waiver) => (
            <tr
              key={waiver.waiver_id}
              data-testid={`admin-waivers-row-${waiver.waiver_id}`}
              className="border-b border-neutral-100 transition last:border-0 hover:bg-neutral-50 dark:border-neutral-800"
            >
              <td className="px-5 py-4">
                <div className="flex items-center gap-3">
                  <Avatar name={waiver.student_name} size={34} />
                  <div>
                    <div className="font-semibold text-rally-base">{waiver.student_name}</div>
                    <div className="text-[12px] text-rally-subtle">
                      {waiver.parent_name || waiver.parent_email || "Parent not linked"}
                    </div>
                  </div>
                </div>
              </td>
              <td className="px-3 py-4 font-mono text-[12px] font-bold tracking-[0.05em] text-rally-ink">
                {waiver.version ?? "-"}
              </td>
              <td className="px-3 py-4 font-mono text-[11px] font-semibold uppercase tracking-[0.05em] text-rally-muted">
                {formatDate(waiver.signed_at)}
              </td>
              <td className="px-3 py-4 text-[12px] text-rally-muted">{waiver.method ?? "-"}</td>
              <td className="px-3 py-4 text-[12px] text-rally-muted">
                {artifactLabel(waiver.artifact_status)}
              </td>
              <td className="px-5 py-4">
                <Chip variant={chipForStatus(waiver.status)} label={labelForStatus(waiver.status)} />
              </td>
              <td className="px-5 py-4">
                {waiver.signature_id ? (
                  <Link
                    href={`/admin/waivers/signatures/${encodeURIComponent(waiver.signature_id)}`}
                    className="text-sm font-semibold text-rally-cobalt hover:underline"
                  >
                    Open signed record
                  </Link>
                ) : (
                  <span className="text-[12px] text-rally-subtle">Not signed</span>
                )}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function artifactLabel(status: string | null | undefined): string {
  if (status === "stored") return "Stored";
  if (status === "stored_reference") return "Stored reference";
  return "Unavailable";
}

function chipForTemplate(template: AdminWaiverTemplateManagementView) {
  if (template.status === "draft") return "draft";
  if (template.status === "active") return "enrolled";
  return "paused";
}

function chipForStatus(status: AdminWaiverStatus) {
  if (status === "signed") return "enrolled";
  if (status === "pending") return "pending";
  if (status === "expiring") return "pending";
  return "paused";
}

function labelForStatus(status: AdminWaiverStatus) {
  if (status === "signed") return "SIGNED";
  if (status === "pending") return "PENDING";
  if (status === "expiring") return "EXPIRING";
  return "OUTDATED";
}

function formatDate(value: string | null | undefined): string {
  if (!value) return "-";
  return new Intl.DateTimeFormat("en-US", {
    month: "short",
    day: "2-digit",
    year: "numeric",
  }).format(new Date(value));
}

function formatPercent(value: number | null | undefined): string | null {
  if (value == null) return null;
  return `${Math.round(value * 100)}% of active students`;
}
