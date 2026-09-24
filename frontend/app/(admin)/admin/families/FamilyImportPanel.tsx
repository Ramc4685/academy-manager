"use client";

/**
 * Roadmap L8b: import families and students from a CSV, on the Families page.
 *
 * Three steps, each the backend's (L8a, `lib/api/admin-family-import.ts`):
 * choose a file, check it (a dry run that writes nothing and answers one
 * result per row), then import after a second look. The page never decides
 * what a row becomes: it shows the backend's plan and sends the batch id back.
 * A commit the backend refuses because the data changed is re-checked with
 * the same file, never retried blind.
 */

import { useMemo, useRef, useState, type ChangeEvent } from "react";
import type { Route } from "next";
import Link from "next/link";
import { useMutation } from "@tanstack/react-query";
import { Download, Upload } from "lucide-react";

import {
  checkImportFile,
  commitFamilyImport,
  commitResultLine,
  importErrorMessage,
  importTemplateCsv,
  needsRecheck,
  previewFamilyImport,
  previewSummaryLine,
  rowStatusLabel,
  type ImportBatch,
  type ImportCommitResult,
  type ImportRow,
} from "@/lib/api/admin-family-import";

import { Button } from "@/components/ds/button";
import { Card } from "@/components/ds/card";
import { Overline } from "@/components/ds/typography";
import { Th } from "@/components/ds/dialog-chrome";
import { ErrorNotice } from "@/components/ds/error-notice";
import { ConfirmActionDialog } from "@/components/admin/confirm-action-dialog";

interface ChosenFile {
  name: string;
  text: string;
}

const STATUS_CLASS: Record<ImportRow["status"], string> = {
  create: "bg-status-green-50 text-status-green-800",
  skip: "bg-status-slate-100 text-status-slate-700",
  error: "bg-status-red-50 text-status-red-800",
};

export function FamilyImportPanel({ onImported }: { onImported: () => void }) {
  const [open, setOpen] = useState(false);
  const [file, setFile] = useState<ChosenFile | null>(null);
  const [fileError, setFileError] = useState<string | null>(null);
  const [batch, setBatch] = useState<ImportBatch | null>(null);
  const [result, setResult] = useState<ImportCommitResult | null>(null);
  const [confirmOpen, setConfirmOpen] = useState(false);
  const [commitError, setCommitError] = useState<string | null>(null);
  const [recheck, setRecheck] = useState(false);
  const [onlyProblems, setOnlyProblems] = useState(false);
  const inputRef = useRef<HTMLInputElement>(null);

  const preview = useMutation({
    mutationFn: (chosen: ChosenFile) =>
      previewFamilyImport({ csv: chosen.text, filename: chosen.name }),
    onSuccess: (next) => {
      setBatch(next);
      setCommitError(null);
      setRecheck(false);
      setOnlyProblems(next.summary.rows_error > 0);
    },
  });

  const commit = useMutation({
    mutationFn: (importBatchId: string) => commitFamilyImport(importBatchId),
    onSuccess: (done) => {
      setConfirmOpen(false);
      setResult(done);
      setBatch(null);
      setFile(null);
      onImported();
    },
    onError: (error) => {
      setConfirmOpen(false);
      setCommitError(importErrorMessage(error));
      setRecheck(needsRecheck(error));
    },
  });

  const reset = () => {
    setFile(null);
    setFileError(null);
    setBatch(null);
    setResult(null);
    setCommitError(null);
    setRecheck(false);
    preview.reset();
    commit.reset();
    if (inputRef.current) inputRef.current.value = "";
  };

  const onChoose = async (event: ChangeEvent<HTMLInputElement>) => {
    const chosen = event.target.files?.[0];
    setBatch(null);
    setResult(null);
    setCommitError(null);
    preview.reset();
    if (!chosen) {
      setFile(null);
      return;
    }
    const check = checkImportFile(chosen);
    if (!check.ok) {
      setFile(null);
      setFileError(check.message);
      return;
    }
    setFileError(null);
    try {
      setFile({ name: chosen.name, text: await chosen.text() });
    } catch {
      setFile(null);
      setFileError("This file could not be read. Save it again as a CSV and retry.");
    }
  };

  const downloadTemplate = () => {
    const blob = new Blob([importTemplateCsv()], { type: "text/csv;charset=utf-8" });
    const url = URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.href = url;
    link.download = "families-import-template.csv";
    document.body.appendChild(link);
    link.click();
    link.remove();
    window.setTimeout(() => URL.revokeObjectURL(url), 0);
  };

  const rows = useMemo(
    () => (batch ? (onlyProblems ? batch.rows.filter((r) => r.status === "error") : batch.rows) : []),
    [batch, onlyProblems],
  );

  if (!open) {
    return (
      <div>
        <Button
          type="button"
          size="sm"
          variant="secondary"
          data-testid="admin-families-import-open"
          icon={<Upload className="size-4" aria-hidden="true" />}
          onClick={() => setOpen(true)}
        >
          Import from CSV
        </Button>
      </div>
    );
  }

  const toAdd = batch?.summary.rows_create ?? 0;

  return (
    <Card p={20} data-testid="admin-families-import">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0">
          <Overline>Import families</Overline>
          <h2 className="mt-1 text-base font-semibold text-rally-base">
            Add families and students from a CSV
          </h2>
          <p className="mt-1 max-w-prose text-sm text-rally-muted">
            One row per child: <code>parent_name</code>, <code>student_name</code>, and a{" "}
            <code>parent_email</code> or <code>parent_phone</code>;{" "}
            <code>student_date_of_birth</code> (YYYY-MM-DD) is optional. At most 1,000 rows. Rows
            that match a family already here join it; nobody is emailed and no login is created.
          </p>
        </div>
        <Button
          type="button"
          size="sm"
          variant="ghost"
          data-testid="admin-families-import-close"
          onClick={() => {
            reset();
            setOpen(false);
          }}
        >
          Close
        </Button>
      </div>

      {result ? (
        <div className="mt-4 flex flex-col gap-3" data-testid="admin-families-import-result">
          <p
            role="status"
            className="rounded-md border border-status-green-200 bg-status-green-50 px-4 py-3 text-sm text-status-green-800"
          >
            {commitResultLine(result)}
          </p>
          <div>
            <Button
              type="button"
              size="sm"
              variant="secondary"
              data-testid="admin-families-import-again"
              onClick={reset}
            >
              Import another file
            </Button>
          </div>
        </div>
      ) : (
        <div className="mt-4 flex flex-col gap-4">
          <div className="flex flex-wrap items-center gap-3">
            <label
              htmlFor="admin-families-import-file"
              className="text-sm font-medium text-rally-base"
            >
              CSV file
            </label>
            <input
              ref={inputRef}
              id="admin-families-import-file"
              data-testid="admin-families-import-file"
              type="file"
              accept=".csv,text/csv"
              onChange={(event) => void onChoose(event)}
              className="max-w-full text-sm text-rally-base file:mr-3 file:rounded-md file:border file:border-rally-line file:bg-white file:px-3 file:py-1.5 file:text-sm file:font-medium"
            />
            <Button
              type="button"
              size="sm"
              variant="ghost"
              data-testid="admin-families-import-template"
              icon={<Download className="size-4" aria-hidden="true" />}
              onClick={downloadTemplate}
            >
              Download template
            </Button>
          </div>

          {fileError ? (
            <p role="alert" data-testid="admin-families-import-file-error" className="text-sm text-status-red-800">
              {fileError}
            </p>
          ) : null}

          {file && !batch ? (
            <div>
              <Button
                type="button"
                size="sm"
                data-testid="admin-families-import-preview"
                disabled={preview.isPending}
                onClick={() => preview.mutate(file)}
              >
                {preview.isPending ? "Checking…" : "Check file"}
              </Button>
              <p className="mt-1 text-xs text-rally-subtle">
                Checking writes nothing. You see every row before anything is added.
              </p>
            </div>
          ) : null}

          {preview.isError ? (
            <ErrorNotice
              testId="admin-families-import-preview-error"
              message={importErrorMessage(preview.error)}
              onRetry={file ? () => preview.mutate(file) : undefined}
              retrying={preview.isPending}
            />
          ) : null}

          {batch ? (
            <ImportPreview
              batch={batch}
              rows={rows}
              onlyProblems={onlyProblems}
              onToggleProblems={setOnlyProblems}
            />
          ) : null}

          {commitError ? (
            <ErrorNotice
              testId="admin-families-import-commit-error"
              message={commitError}
              onRetry={recheck && file ? () => preview.mutate(file) : undefined}
              retrying={preview.isPending}
            />
          ) : null}

          {batch ? (
            <div className="flex flex-wrap items-center gap-3">
              <Button
                type="button"
                data-testid="admin-families-import-commit"
                disabled={!batch.can_commit || toAdd === 0 || commit.isPending || recheck}
                onClick={() => setConfirmOpen(true)}
              >
                {toAdd === 0
                  ? "Nothing to import"
                  : `Import ${toAdd.toLocaleString("en-US")} ${toAdd === 1 ? "child" : "children"}`}
              </Button>
              <Button
                type="button"
                variant="secondary"
                data-testid="admin-families-import-choose-another"
                onClick={reset}
              >
                Choose another file
              </Button>
              {!batch.can_commit ? (
                <p className="text-sm text-status-red-800" data-testid="admin-families-import-blocked">
                  Fix the rows with problems in the file, then check it again. Nothing is imported
                  while any row has a problem.
                </p>
              ) : null}
            </div>
          ) : null}
        </div>
      )}

      {batch ? (
        <ConfirmActionDialog
          open={confirmOpen}
          onOpenChange={setConfirmOpen}
          overline="Import families"
          title="Import these students"
          subject={batch.filename ?? "The checked file"}
          consequence={
            <>
              <p>{previewSummaryLine(batch.summary)}.</p>
              <p>
                The rows are checked again against the Families list as it is now. Nobody is
                emailed, no login is created and nothing is charged; invite families from Billing
                Setup when you are ready.
              </p>
            </>
          }
          confirmLabel="Import"
          cancelLabel="Not yet"
          confirmVariant="primary"
          pending={commit.isPending}
          onConfirm={() => commit.mutate(batch.import_batch_id)}
        />
      ) : null}
    </Card>
  );
}

function ImportPreview({
  batch,
  rows,
  onlyProblems,
  onToggleProblems,
}: {
  batch: ImportBatch;
  rows: ImportRow[];
  onlyProblems: boolean;
  onToggleProblems: (value: boolean) => void;
}) {
  const { summary } = batch;
  return (
    <div className="flex flex-col gap-3" data-testid="admin-families-import-preview-result">
      <p
        role="status"
        data-testid="admin-families-import-summary"
        className="text-sm font-medium text-rally-base"
      >
        {previewSummaryLine(summary)}
      </p>
      {summary.rows_error > 0 ? (
        <label className="inline-flex items-center gap-2 text-sm text-rally-muted">
          <input
            type="checkbox"
            data-testid="admin-families-import-only-problems"
            checked={onlyProblems}
            onChange={(event) => onToggleProblems(event.target.checked)}
          />
          Only rows with problems
        </label>
      ) : null}
      <div className="max-h-[28rem] overflow-auto rounded-md border border-rally-line">
        <table className="w-full text-left text-sm" data-testid="admin-families-import-table">
          <caption className="sr-only">One result per row of the file</caption>
          <thead className="sticky top-0 bg-white">
            <tr className="border-b border-neutral-200">
              <Th>Line</Th>
              <Th>Result</Th>
              <Th>Parent</Th>
              <Th>Child</Th>
              <Th>Notes</Th>
            </tr>
          </thead>
          <tbody>
            {rows.map((row) => (
              <tr
                key={row.line}
                data-testid={`admin-families-import-row-${row.line}`}
                className="border-b border-neutral-100 align-top last:border-0"
              >
                <td className="px-3 py-2 font-mono text-xs tabular-nums text-rally-muted">
                  {row.line}
                </td>
                <td className="px-3 py-2">
                  <span
                    className={`whitespace-nowrap rounded-full px-2 py-0.5 text-[11px] font-semibold ${STATUS_CLASS[row.status]}`}
                  >
                    {rowStatusLabel(row)}
                  </span>
                </td>
                <td className="px-3 py-2">
                  <div className="text-rally-base">{row.parent_name || "—"}</div>
                  <div className="break-all text-xs text-rally-muted">
                    {[row.parent_email, row.parent_phone].filter(Boolean).join(" · ") || "No contact"}
                  </div>
                </td>
                <td className="px-3 py-2">
                  <div className="text-rally-base">{row.student_name || "—"}</div>
                  {row.student_date_of_birth ? (
                    <div className="text-xs text-rally-muted">Born {row.student_date_of_birth}</div>
                  ) : null}
                </td>
                <td className="px-3 py-2 text-xs">
                  <RowNotes row={row} />
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

function RowNotes({ row }: { row: ImportRow }) {
  const family =
    row.family_action === "existing" && row.family_name ? (
      row.family_link ? (
        <Link
          href={row.family_link as Route}
          className="font-medium text-rally-cobalt-700 hover:underline"
        >
          {row.family_name}
        </Link>
      ) : (
        <span>{row.family_name}</span>
      )
    ) : null;
  if (row.errors.length === 0 && row.warnings.length === 0 && !family) {
    return <span className="text-rally-subtle">—</span>;
  }
  return (
    <ul className="flex flex-col gap-1">
      {family ? <li className="text-rally-muted">Family: {family}</li> : null}
      {row.errors.map((issue, i) => (
        <li key={`e-${i}`} className="text-status-red-800">
          {issue.message}
        </li>
      ))}
      {row.warnings.map((warning, i) => (
        <li key={`w-${i}`} className="text-status-amber-800">
          {warning}
        </li>
      ))}
    </ul>
  );
}
