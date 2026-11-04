"use client";

/**
 * UIM6 (#449) — bulk-invite parents from a paste or a CSV.
 *
 * Three steps in one dialog: paste/pick rows, preview what will be sent, then
 * read the per-row result. Every created parent gets a real login-invite email,
 * so the preview is explicit about how many emails the submit sends, the submit
 * button is loading-guarded against a double send, and rows that cannot succeed
 * (bad email, over-long name, duplicate inside the batch) are filtered out
 * before the request rather than burned as failures server-side.
 */

import { useRef, useState } from "react";
import type { ChangeEvent } from "react";
import * as Dialog from "@radix-ui/react-dialog";
import { useMutation } from "@tanstack/react-query";
import { Upload } from "lucide-react";

import { bulkInviteParents, type BulkInviteResponse } from "@/lib/api/admin";
import {
  BULK_INVITE_MAX_ROWS,
  parseBulkInviteText,
  toBulkInviteItems,
  type BulkInviteItem,
} from "@/lib/admin/bulk-invite-parse";
import { Button } from "@/components/ds/button";
import { Chip, type ChipVariant } from "@/components/ds/chip";

const PLACEHOLDER = "ana@example.com, Ana Parent\nbo@example.com, Bo Parent";

const STATUS_VARIANT: Record<string, ChipVariant> = {
  created: "enrolled",
  skipped: "manual",
  failed: "failed",
};

export function BulkInviteDialog({
  open,
  onOpenChange,
  onInvited,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  /** Called after a batch returns so the caller can refresh the directory. */
  onInvited: () => void;
}) {
  const [text, setText] = useState("");
  const [fileName, setFileName] = useState<string | null>(null);
  const [result, setResult] = useState<BulkInviteResponse | null>(null);
  /** Exactly what the last submit sent, so "retry failed" never re-derives names. */
  const [submitted, setSubmitted] = useState<BulkInviteItem[]>([]);
  const [error, setError] = useState<string | null>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);

  const parsed = parseBulkInviteText(text);
  const items = toBulkInviteItems(parsed);

  const mutation = useMutation({
    mutationFn: (users: BulkInviteItem[]) => bulkInviteParents({ users }),
    onSuccess: (response) => {
      setResult(response);
      setError(null);
      onInvited();
    },
    onError: (err: unknown) => {
      setError(err instanceof Error ? err.message : "Could not send the invites.");
    },
  });

  function reset() {
    setText("");
    setFileName(null);
    setResult(null);
    setSubmitted([]);
    setError(null);
    mutation.reset();
    if (fileInputRef.current) fileInputRef.current.value = "";
  }

  function close() {
    reset();
    onOpenChange(false);
  }

  /** Re-seed the input with only the rows that failed, so a retry re-sends nothing else. */
  function retryFailed(response: BulkInviteResponse) {
    const failedRows = response.results.filter((row) => row.status === "failed");
    const byEmail = new Map(submitted.map((item) => [item.email, item.display_name]));
    reset();
    setText(
      failedRows
        .map((row) => `${row.email}, ${byEmail.get(row.email) ?? ""}`.trim().replace(/,$/, ""))
        .join("\n"),
    );
  }

  async function onFilePicked(event: ChangeEvent<HTMLInputElement>) {
    const file = event.target.files?.[0];
    if (!file) return;
    const contents = await file.text();
    setFileName(file.name);
    // Append rather than replace so a paste and a file can be combined.
    setText((current) => (current.trim() ? `${current.trim()}\n${contents}` : contents));
  }

  const blocked = parsed.overLimit || items.length === 0;

  return (
    <Dialog.Root
      open={open}
      onOpenChange={(next) => {
        if (!next) reset();
        onOpenChange(next);
      }}
    >
      <Dialog.Portal>
        <Dialog.Overlay className="fixed inset-0 z-40 bg-neutral-950/40" />
        <Dialog.Content
          data-testid="bulk-invite-dialog"
          className="fixed left-1/2 top-1/2 z-50 flex max-h-[90vh] w-[min(94vw,640px)] -translate-x-1/2 -translate-y-1/2 flex-col overflow-hidden rounded-lg border border-rally-line bg-white p-5 shadow-xl focus:outline-none"
        >
          <Dialog.Title className="font-display text-xl font-bold text-rally-ink">
            Bulk invite parents
          </Dialog.Title>

          {result ? (
            <ResultStep
              result={result}
              onDone={close}
              onInviteMore={reset}
              onRetryFailed={() => retryFailed(result)}
            />
          ) : (
            <form
              className="mt-4 flex min-h-0 flex-col gap-4 overflow-y-auto"
              onSubmit={(event) => {
                event.preventDefault();
                if (blocked || mutation.isPending) return;
                setError(null);
                setSubmitted(items);
                mutation.mutate(items);
              }}
            >
              <Dialog.Description className="text-sm text-rally-muted">
                One parent per line as <code>email, name</code> (a <code>name, email</code> CSV
                works too). Up to {BULK_INVITE_MAX_ROWS} per batch — each new parent is sent a
                login invite.
              </Dialog.Description>

              <label className="block" htmlFor="bulk-invite-textarea">
                <span className="mb-1.5 block font-mono text-[10px] font-bold uppercase tracking-overline text-rally-muted">
                  Parents
                </span>
                <textarea
                  id="bulk-invite-textarea"
                  data-testid="bulk-invite-textarea"
                  value={text}
                  onChange={(event) => setText(event.target.value)}
                  rows={6}
                  placeholder={PLACEHOLDER}
                  className="w-full rounded-md border border-neutral-200 bg-white p-3 font-mono text-xs text-rally-base outline-none focus:border-rally-cobalt-600 focus:ring-2 focus:ring-rally-cobalt-600/15"
                />
              </label>

              <div className="flex flex-wrap items-center gap-3">
                <Button
                  type="button"
                  variant="secondary"
                  size="sm"
                  icon={<Upload className="size-4" aria-hidden="true" />}
                  onClick={() => fileInputRef.current?.click()}
                >
                  Upload CSV
                </Button>
                <input
                  ref={fileInputRef}
                  data-testid="bulk-invite-file"
                  type="file"
                  accept=".csv,text/csv,text/plain"
                  className="sr-only"
                  aria-label="Upload CSV"
                  onChange={(event) => {
                    void onFilePicked(event);
                  }}
                />
                {fileName && (
                  <span className="text-xs text-rally-muted" data-testid="bulk-invite-file-name">
                    {fileName}
                  </span>
                )}
              </div>

              <PreviewStep parsed={parsed} />

              {parsed.overLimit && (
                <p
                  role="alert"
                  data-testid="bulk-invite-limit-error"
                  className="rounded-md bg-red-50 p-3 text-sm text-red-700"
                >
                  {parsed.validCount} parents is over the {BULK_INVITE_MAX_ROWS} per batch limit.
                  Remove {parsed.validCount - BULK_INVITE_MAX_ROWS} and send the rest separately.
                </p>
              )}

              {error && (
                <p
                  role="alert"
                  data-testid="bulk-invite-error"
                  className="rounded-md bg-red-50 p-3 text-sm text-red-700"
                >
                  {error}
                </p>
              )}

              <div className="flex justify-end gap-2 pt-2">
                <Button type="button" variant="secondary" onClick={close}>
                  Cancel
                </Button>
                <Button
                  type="submit"
                  data-testid="bulk-invite-submit"
                  disabled={blocked || mutation.isPending}
                >
                  {mutation.isPending
                    ? "Sending invites..."
                    : `Send ${items.length} invite${items.length === 1 ? "" : "s"}`}
                </Button>
              </div>
            </form>
          )}
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  );
}

function PreviewStep({ parsed }: { parsed: ReturnType<typeof parseBulkInviteText> }) {
  if (parsed.rows.length === 0) return null;

  return (
    <div className="space-y-2">
      <p className="text-sm text-rally-base" data-testid="bulk-invite-preview-count">
        {parsed.validCount} to invite
        {parsed.duplicateCount > 0 ? ` · ${parsed.duplicateCount} duplicate` : ""}
        {parsed.invalidCount > 0 ? ` · ${parsed.invalidCount} invalid` : ""}
      </p>
      <div className="max-h-56 overflow-y-auto rounded-md border border-rally-line">
        <table className="w-full text-sm" data-testid="bulk-invite-preview">
          <thead>
            <tr className="border-b border-neutral-200 text-left dark:border-neutral-800">
              <th className="px-2 py-2 font-mono text-[10px] font-bold uppercase tracking-overline text-rally-muted">
                Email
              </th>
              <th className="px-2 py-2 font-mono text-[10px] font-bold uppercase tracking-overline text-rally-muted">
                Name
              </th>
              <th className="px-2 py-2 font-mono text-[10px] font-bold uppercase tracking-overline text-rally-muted">
                Status
              </th>
            </tr>
          </thead>
          <tbody>
            {parsed.rows.map((row) => (
              <tr
                key={`${row.line}-${row.email}`}
                data-testid={`bulk-invite-preview-row-${row.line}`}
                className="border-b border-neutral-100 last:border-0 dark:border-neutral-800"
              >
                <td className="px-2 py-2 text-rally-base">{row.email}</td>
                <td className="px-2 py-2 text-rally-muted">{row.display_name}</td>
                <td className="px-2 py-2">
                  {row.error ? (
                    <span className="text-xs text-status-red-800">{row.error}</span>
                  ) : row.duplicate ? (
                    <span className="text-xs text-rally-muted">Duplicate in this list</span>
                  ) : (
                    <span className="text-xs text-rally-muted">Will invite</span>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

function ResultStep({
  result,
  onDone,
  onInviteMore,
  onRetryFailed,
}: {
  result: BulkInviteResponse;
  onDone: () => void;
  onInviteMore: () => void;
  onRetryFailed: () => void;
}) {
  return (
    <div className="mt-4 flex min-h-0 flex-col gap-4 overflow-y-auto" data-testid="bulk-invite-results">
      <p className="text-sm text-rally-base" data-testid="bulk-invite-result-summary">
        {result.created} created · {result.skipped} skipped · {result.failed} failed
      </p>
      <div className="max-h-72 overflow-y-auto rounded-md border border-rally-line">
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b border-neutral-200 text-left dark:border-neutral-800">
              <th className="px-2 py-2 font-mono text-[10px] font-bold uppercase tracking-overline text-rally-muted">
                Email
              </th>
              <th className="px-2 py-2 font-mono text-[10px] font-bold uppercase tracking-overline text-rally-muted">
                Result
              </th>
              <th className="px-2 py-2 font-mono text-[10px] font-bold uppercase tracking-overline text-rally-muted">
                Detail
              </th>
            </tr>
          </thead>
          <tbody>
            {result.results.map((row) => (
              <tr
                key={row.email}
                data-testid={`bulk-invite-result-row-${row.email}`}
                className="border-b border-neutral-100 last:border-0 dark:border-neutral-800"
              >
                <td className="px-2 py-2 text-rally-base">{row.email}</td>
                <td className="px-2 py-2">
                  <Chip
                    variant={STATUS_VARIANT[row.status] ?? "waitlist"}
                    label={row.status.toUpperCase()}
                  />
                </td>
                <td className="px-2 py-2 text-rally-muted">{row.detail ?? "-"}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <div className="flex justify-end gap-2 pt-2">
        {result.failed > 0 && (
          <Button
            type="button"
            variant="secondary"
            data-testid="bulk-invite-retry-failed"
            onClick={onRetryFailed}
          >
            Retry {result.failed} failed
          </Button>
        )}
        <Button type="button" variant="secondary" onClick={onInviteMore}>
          Invite more
        </Button>
        <Button type="button" data-testid="bulk-invite-done" onClick={onDone}>
          Done
        </Button>
      </div>
    </div>
  );
}
