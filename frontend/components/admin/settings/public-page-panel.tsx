"use client";

import { useEffect, useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import {
  archiveAdminProgram,
  assignAdminClassProgram,
  createAdminProgram,
  getAdminPublicPageSettings,
  listAdminClassPublicProfiles,
  listAdminPrograms,
  renameAdminProgram,
  updateAdminClassPublicFields,
  updateAdminPublicPageSettings,
  type AdminClassPublicProfileView,
  type AdminProgramView,
  type PublicCoachDisplay,
  type PublicPricePeriod,
  type UpdateAdminClassPublicFieldsRequest,
} from "@/lib/api/admin";
import {
  COACH_DISPLAY_LABEL,
  PRICE_PERIOD_LABEL,
  listableClasses,
  privacyUrlError,
  programOptions,
  publicPagePayload,
  toPublicPageForm,
  viewPageHref,
  type PublicPageForm,
} from "@/lib/public-page/admin-settings";
import { queryKeys } from "@/lib/query/keys";
import {
  Button,
  Card,
  EmptyState,
  FormField,
  Overline,
  TableSkeleton,
  Th,
  fieldDescribedBy,
} from "@/components/ds";
import { useReportSettingsDirty } from "@/components/admin/settings/settings-dirty-context";
import { SavedNote, savedAtNow } from "@/components/admin/settings/saved-note";

const PRICE_PERIODS = Object.keys(PRICE_PERIOD_LABEL) as PublicPricePeriod[];
const COACH_DISPLAYS = Object.keys(COACH_DISPLAY_LABEL) as PublicCoachDisplay[];

const SELECT_CLASS =
  "min-h-11 rounded-md border border-rally-line bg-white px-2 py-1 text-sm text-rally-ink disabled:opacity-50";

/**
 * Settings → Public page (Lane B5).
 *
 * The page-level switches are a draft saved with one button and guarded by
 * the settings unsaved-changes guard, like every other settings panel. The
 * program and per-class controls below save on change, like the rows in
 * Session types, so they never leave a draft behind.
 */
export function PublicPagePanel() {
  return (
    <section data-testid="admin-settings-public-page" className="space-y-6">
      <PageSettingsCard />
      <ProgramsCard />
      <ClassesCard />
    </section>
  );
}

function PageSettingsCard() {
  const queryClient = useQueryClient();
  const [form, setForm] = useState<PublicPageForm>(() => toPublicPageForm(null));
  const [savedAt, setSavedAt] = useState<string | null>(null);
  const [location, setLocation] = useState<{ origin: string; host: string } | null>(null);
  const query = useQuery({
    queryKey: queryKeys.admin.publicPage(),
    queryFn: getAdminPublicPageSettings,
  });
  const original = useMemo(() => toPublicPageForm(query.data), [query.data]);

  useEffect(() => {
    if (query.data) setForm(toPublicPageForm(query.data));
  }, [query.data]);

  useEffect(() => {
    setLocation({ origin: window.location.origin, host: window.location.host });
  }, []);

  const payload = publicPagePayload(original, form);
  const dirty = Object.keys(payload).length > 0;
  useReportSettingsDirty("public-page", dirty);
  const urlError = privacyUrlError(form.privacy_notice_url);

  const mutation = useMutation({
    mutationFn: () => updateAdminPublicPageSettings(payload),
    onSuccess: (data) => {
      setSavedAt(savedAtNow());
      queryClient.setQueryData(queryKeys.admin.publicPage(), data);
    },
  });

  const href = viewPageHref(query.data?.public_url ?? null, location);
  const livePublished = query.data?.published ?? false;

  return (
    <Card p={24} className="max-w-3xl">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <Overline>Public page</Overline>
          <p className="mt-1 text-sm text-rally-muted">
            Your academy&rsquo;s web page for new families: programs, classes and a Book a
            free trial form.
          </p>
        </div>
        {href ? (
          <a
            href={href}
            target="_blank"
            rel="noopener noreferrer"
            data-testid="public-page-view-link"
            className="inline-flex min-h-11 items-center rounded-md border border-rally-line px-4 text-sm font-semibold text-rally-cobalt-700 underline-offset-2 hover:underline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-rally-cobalt-600"
          >
            View page<span className="sr-only"> (opens in a new tab)</span>
          </a>
        ) : (
          <p className="max-w-xs text-xs text-rally-subtle" data-testid="public-page-no-address">
            Your page&rsquo;s web address is not set up yet. CourtMastr support connects it.
          </p>
        )}
      </div>
      <p
        className="mt-4 rounded-md bg-rally-paper px-4 py-3 text-sm text-rally-ink"
        data-testid="public-page-live-note"
        role="status"
      >
        {livePublished
          ? "Your page is live. Anyone with the link can see it."
          : "Your page is not live. It goes live only when Publish page is on and saved."}
      </p>

      <div className="mt-5 grid gap-3">
        <Toggle
          testId="public-page-published"
          label="Publish page"
          hint="Off keeps the page private; visitors see a “nothing published yet” page."
          checked={form.published}
          onChange={(checked) => setForm((prev) => ({ ...prev, published: checked }))}
        />
        <Toggle
          testId="public-page-show-price"
          label="Show prices"
          hint="A price band per class, never an invoice amount."
          checked={form.show_price}
          onChange={(checked) => setForm((prev) => ({ ...prev, show_price: checked }))}
        />
        <Toggle
          testId="public-page-show-availability"
          label="Show seat availability"
          hint="“Seats open”, “A few seats left” or “Full, join waitlist”; never exact counts."
          checked={form.show_availability}
          onChange={(checked) => setForm((prev) => ({ ...prev, show_availability: checked }))}
        />
        <Toggle
          testId="public-page-trials-open"
          label="Accept free trial requests"
          hint="Off hides the Book a free trial form and says trials are closed."
          checked={form.trials_open}
          onChange={(checked) => setForm((prev) => ({ ...prev, trials_open: checked }))}
        />
        <label className="flex min-h-12 items-center justify-between gap-4 rounded-md border border-rally-line px-4 text-sm font-medium text-rally-ink">
          <span>
            Price period
            <span className="block text-xs font-normal text-rally-subtle">
              Used for every class unless the class sets its own below.
            </span>
          </span>
          <select
            data-testid="public-page-price-period"
            value={form.price_period_default}
            onChange={(event) =>
              setForm((prev) => ({
                ...prev,
                price_period_default: event.target.value as PublicPricePeriod,
              }))
            }
            className={SELECT_CLASS}
          >
            {PRICE_PERIODS.map((period) => (
              <option key={period} value={period}>
                {PRICE_PERIOD_LABEL[period]}
              </option>
            ))}
          </select>
        </label>
        <FormField
          label="Privacy notice link"
          htmlFor="public-page-privacy-url"
          hint="Shown next to the trial form. Leave blank if you do not have one."
          error={urlError}
        >
          <input
            id="public-page-privacy-url"
            data-testid="public-page-privacy-url"
            type="url"
            inputMode="url"
            placeholder="https://"
            value={form.privacy_notice_url}
            aria-invalid={urlError ? true : undefined}
            aria-describedby={fieldDescribedBy("public-page-privacy-url", {
              hint: true,
              error: urlError,
            })}
            onChange={(event) =>
              setForm((prev) => ({ ...prev, privacy_notice_url: event.target.value }))
            }
            className="min-h-11 w-full rounded-md border border-rally-line bg-white px-3 text-sm"
          />
        </FormField>
      </div>

      <div className="mt-6 flex flex-wrap items-center gap-3">
        <Button
          variant={dirty ? "volt" : "secondary"}
          size="sm"
          disabled={!dirty || Boolean(urlError) || mutation.isPending || query.isPending}
          onClick={() => mutation.mutate()}
          data-testid="public-page-save"
        >
          {mutation.isPending ? "Saving..." : "Save changes"}
        </Button>
        <SavedNote at={savedAt} />
        {(query.isError || mutation.isError) && (
          <p role="alert" className="text-sm font-medium text-status-red-800">
            {(mutation.error ?? query.error)?.message}
          </p>
        )}
      </div>
    </Card>
  );
}

function ProgramsCard() {
  const queryClient = useQueryClient();
  const [newName, setNewName] = useState("");
  const [renaming, setRenaming] = useState<{ id: string; name: string } | null>(null);
  const query = useQuery({
    queryKey: queryKeys.admin.programs(),
    queryFn: () => listAdminPrograms(),
  });
  const invalidate = () =>
    queryClient.invalidateQueries({ queryKey: queryKeys.admin.programs() });

  // A typed-but-unsaved program name is a draft too.
  useReportSettingsDirty(
    "public-page-programs",
    newName.trim() !== "" || (renaming !== null && renaming.name.trim() !== "")
  );

  const create = useMutation({
    mutationFn: () => createAdminProgram({ name: newName.trim() }),
    onSuccess: () => {
      setNewName("");
      void invalidate();
    },
  });
  const rename = useMutation({
    mutationFn: (args: { id: string; name: string }) => renameAdminProgram(args.id, args.name),
    onSuccess: () => {
      setRenaming(null);
      void invalidate();
    },
  });
  const archive = useMutation({
    mutationFn: (programId: string) => archiveAdminProgram(programId),
    onSuccess: () => {
      void invalidate();
      // Classes keep their program_id; the class list marks it "(archived)".
      void queryClient.invalidateQueries({ queryKey: queryKeys.admin.classPublicProfiles() });
    },
  });

  const programs = query.data?.programs ?? [];
  const error = create.error ?? rename.error ?? archive.error;

  return (
    <Card p={24} className="max-w-3xl" data-testid="public-page-programs">
      <Overline>Programs</Overline>
      <p className="mt-1 text-sm text-rally-muted">
        Group your classes on the page, for example Juniors or Adult beginners.
      </p>
      <form
        className="mt-4 flex flex-wrap items-end gap-3"
        onSubmit={(event) => {
          event.preventDefault();
          if (newName.trim()) create.mutate();
        }}
      >
        <FormField label="New program name" htmlFor="public-page-new-program" className="grow">
          <input
            id="public-page-new-program"
            data-testid="public-page-new-program"
            value={newName}
            maxLength={80}
            onChange={(event) => setNewName(event.target.value)}
            className="min-h-11 w-full rounded-md border border-rally-line bg-white px-3 text-sm"
          />
        </FormField>
        <Button
          type="submit"
          variant="secondary"
          size="sm"
          disabled={!newName.trim() || create.isPending}
          data-testid="public-page-add-program"
        >
          {create.isPending ? "Adding..." : "Add program"}
        </Button>
      </form>
      {query.isPending ? (
        <div className="mt-4">
          <TableSkeleton rows={2} cols={2} />
        </div>
      ) : programs.length === 0 ? (
        <p className="mt-4 text-sm text-rally-subtle" data-testid="public-page-programs-empty">
          No programs yet. Classes without a program are listed on their own.
        </p>
      ) : (
        <ul className="mt-4 divide-y divide-rally-line rounded-md border border-rally-line">
          {programs.map((program) => (
            <li
              key={program.program_id}
              data-testid="public-page-program-row"
              className="flex flex-wrap items-center justify-between gap-3 px-4 py-2"
            >
              {renaming?.id === program.program_id ? (
                <form
                  className="flex grow flex-wrap items-center gap-2"
                  onSubmit={(event) => {
                    event.preventDefault();
                    if (renaming.name.trim()) {
                      rename.mutate({ id: program.program_id, name: renaming.name.trim() });
                    }
                  }}
                >
                  <label className="sr-only" htmlFor={`rename-${program.program_id}`}>
                    Program name
                  </label>
                  <input
                    id={`rename-${program.program_id}`}
                    data-testid="public-page-rename-input"
                    value={renaming.name}
                    maxLength={80}
                    autoFocus
                    onChange={(event) =>
                      setRenaming({ id: program.program_id, name: event.target.value })
                    }
                    className="min-h-11 grow rounded-md border border-rally-line bg-white px-3 text-sm"
                  />
                  <Button
                    type="submit"
                    variant="volt"
                    size="sm"
                    disabled={!renaming.name.trim() || rename.isPending}
                  >
                    Save name
                  </Button>
                  <Button variant="secondary" size="sm" onClick={() => setRenaming(null)}>
                    Cancel
                  </Button>
                </form>
              ) : (
                <>
                  <span className="font-semibold text-rally-ink">{program.name}</span>
                  <div className="flex gap-2">
                    <Button
                      variant="secondary"
                      size="sm"
                      onClick={() => setRenaming({ id: program.program_id, name: program.name })}
                      aria-label={`Rename ${program.name}`}
                    >
                      Rename
                    </Button>
                    <Button
                      variant="danger"
                      size="sm"
                      disabled={archive.isPending && archive.variables === program.program_id}
                      onClick={() => archive.mutate(program.program_id)}
                      aria-label={`Archive ${program.name}`}
                    >
                      Archive
                    </Button>
                  </div>
                </>
              )}
            </li>
          ))}
        </ul>
      )}
      {error && (
        <p role="alert" className="mt-3 text-sm font-medium text-status-red-800">
          {error.message}
        </p>
      )}
    </Card>
  );
}

type RowChange =
  | { kind: "fields"; sessionId: string; fields: UpdateAdminClassPublicFieldsRequest }
  | { kind: "program"; sessionId: string; programId: string | null };

function ClassesCard() {
  const queryClient = useQueryClient();
  const classes = useQuery({
    queryKey: queryKeys.admin.classPublicProfiles(),
    queryFn: listAdminClassPublicProfiles,
  });
  // Archived programs too, so a class still pointing at one says so.
  const programs = useQuery({
    queryKey: queryKeys.admin.programsWithArchived(),
    queryFn: () => listAdminPrograms({ includeArchived: true }),
  });

  const change = useMutation({
    mutationFn: (req: RowChange) =>
      req.kind === "fields"
        ? updateAdminClassPublicFields(req.sessionId, req.fields)
        : assignAdminClassProgram(req.sessionId, req.programId),
    onSuccess: (row) => replaceRow(row.session_id, () => row),
    onError: () =>
      void queryClient.invalidateQueries({ queryKey: queryKeys.admin.classPublicProfiles() }),
  });

  function replaceRow(
    sessionId: string,
    update: (row: AdminClassPublicProfileView) => AdminClassPublicProfileView
  ) {
    queryClient.setQueryData<{ classes: AdminClassPublicProfileView[] }>(
      queryKeys.admin.classPublicProfiles(),
      (prev) =>
        prev && {
          classes: prev.classes.map((c) => (c.session_id === sessionId ? update(c) : c)),
        }
    );
  }

  const rows = listableClasses(classes.data?.classes ?? []);
  const allPrograms = programs.data?.programs ?? [];
  const pendingId = change.isPending ? change.variables?.sessionId : undefined;
  const failedId = change.isError ? change.variables?.sessionId : undefined;

  return (
    <Card p={0} data-testid="public-page-classes">
      <div className="p-6 pb-3">
        <Overline>Classes on the page</Overline>
        <p className="mt-1 text-sm text-rally-muted">
          Classes are private until you switch them on. Each change saves right away.
        </p>
      </div>
      {classes.isPending ? (
        <div className="p-5">
          <TableSkeleton rows={3} cols={5} />
        </div>
      ) : classes.isError ? (
        <p role="alert" className="p-5 text-sm text-status-red-800">
          Could not load classes.
        </p>
      ) : rows.length === 0 ? (
        <EmptyState
          data-testid="public-page-classes-empty"
          title="No classes yet"
          description="Classes you create under Sessions appear here, private until you switch them on."
        />
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full min-w-[720px] text-sm">
            <thead>
              <tr className="border-b border-rally-line">
                <Th>Class</Th>
                <Th>On the page</Th>
                <Th>Program</Th>
                <Th>Price shown</Th>
                <Th>Coach name</Th>
              </tr>
            </thead>
            <tbody>
              {rows.map((row) => (
                <ClassRow
                  key={row.session_id}
                  row={row}
                  programs={allPrograms}
                  pending={pendingId === row.session_id}
                  failed={failedId === row.session_id}
                  onChange={(req) => {
                    // Optimistic and synchronous, so a switch flips under the
                    // finger; a failure refetches the server's truth and the
                    // row says it could not save.
                    const patch: Partial<AdminClassPublicProfileView> =
                      req.kind === "fields" ? req.fields : { program_id: req.programId };
                    replaceRow(req.sessionId, (current) => ({ ...current, ...patch }));
                    change.mutate(req);
                  }}
                />
              ))}
            </tbody>
          </table>
        </div>
      )}
    </Card>
  );
}

function ClassRow({
  row,
  programs,
  pending,
  failed,
  onChange,
}: {
  row: AdminClassPublicProfileView;
  programs: AdminProgramView[];
  pending: boolean;
  failed: boolean;
  onChange: (req: RowChange) => void;
}) {
  const title = row.title ?? "Untitled class";
  const options = programOptions(programs, row.program_id);
  return (
    <tr
      data-testid="public-page-class-row"
      data-session-id={row.session_id}
      className="border-b border-rally-line last:border-0"
    >
      <td className="px-4 py-3">
        <span className="font-semibold text-rally-ink">{title}</span>
        {(row.status === "cancelled" || row.status === "completed") && (
          <p className="text-xs text-rally-subtle">
            {row.status === "cancelled" ? "Cancelled" : "Ended"}: not shown on the page
          </p>
        )}
        {failed && (
          <p role="alert" className="mt-1 text-xs text-status-red-800">
            Could not save this class. Try again.
          </p>
        )}
      </td>
      <td className="px-4 py-3">
        <label className="inline-flex min-h-11 items-center gap-2">
          <input
            type="checkbox"
            role="switch"
            data-testid="public-page-class-published"
            checked={row.published}
            disabled={pending}
            onChange={(event) =>
              onChange({
                kind: "fields",
                sessionId: row.session_id,
                fields: { published: event.target.checked },
              })
            }
            className="size-4 accent-blue-600"
          />
          <span>{row.published ? "Shown" : "Private"}</span>
          <span className="sr-only"> for {title}</span>
        </label>
      </td>
      <td className="px-4 py-3">
        <select
          aria-label={`Program for ${title}`}
          data-testid="public-page-class-program"
          value={row.program_id ?? ""}
          disabled={pending}
          onChange={(event) =>
            onChange({
              kind: "program",
              sessionId: row.session_id,
              programId: event.target.value || null,
            })
          }
          className={SELECT_CLASS}
        >
          <option value="">No program</option>
          {options.map((option) => (
            <option key={option.value} value={option.value}>
              {option.label}
            </option>
          ))}
        </select>
      </td>
      <td className="px-4 py-3">
        <select
          aria-label={`Price period for ${title}`}
          data-testid="public-page-class-price-period"
          value={row.price_period ?? ""}
          disabled={pending}
          onChange={(event) =>
            onChange({
              kind: "fields",
              sessionId: row.session_id,
              fields: {
                price_period: (event.target.value || null) as PublicPricePeriod | null,
              },
            })
          }
          className={SELECT_CLASS}
        >
          <option value="">Academy default</option>
          {PRICE_PERIODS.map((period) => (
            <option key={period} value={period}>
              {PRICE_PERIOD_LABEL[period]}
            </option>
          ))}
        </select>
      </td>
      <td className="px-4 py-3">
        <select
          aria-label={`Coach name for ${title}`}
          data-testid="public-page-class-coach-display"
          value={row.coach_display}
          disabled={pending}
          onChange={(event) =>
            onChange({
              kind: "fields",
              sessionId: row.session_id,
              fields: { coach_display: event.target.value as PublicCoachDisplay },
            })
          }
          className={SELECT_CLASS}
        >
          {COACH_DISPLAYS.map((display) => (
            <option key={display} value={display}>
              {COACH_DISPLAY_LABEL[display]}
            </option>
          ))}
        </select>
      </td>
    </tr>
  );
}

function Toggle({
  label,
  hint,
  checked,
  onChange,
  testId,
}: {
  label: string;
  hint: string;
  checked: boolean;
  onChange: (checked: boolean) => void;
  testId: string;
}) {
  return (
    <label className="flex min-h-12 items-center justify-between gap-4 rounded-md border border-rally-line px-4 py-2 text-sm font-medium text-rally-ink">
      <span>
        {label}
        <span className="block text-xs font-normal text-rally-subtle">{hint}</span>
      </span>
      <input
        type="checkbox"
        role="switch"
        data-testid={testId}
        checked={checked}
        onChange={(event) => onChange(event.target.checked)}
        className="size-4 shrink-0 accent-blue-600"
      />
    </label>
  );
}
