"use client";

import { useRef, useState } from "react";

import { Button } from "@/components/ds/button";
import { submitPhotoFile } from "@/lib/public-page/content-settings";

/**
 * Photo upload control for the Photos & details card (same pattern as the
 * logo upload). It only reports the new URL; saving still goes through the
 * card's Save button. `blockedReason` disables the picker (for example, the
 * gallery consent box is not ticked yet) so the file dialog never opens.
 */
export function PhotoUpload({
  testId,
  label,
  buttonLabel = "Choose photo",
  hint = "PNG or JPG, up to 5 MB.",
  upload,
  onUploaded,
  blockedReason = null,
}: {
  testId: string;
  label: string;
  buttonLabel?: string;
  hint?: string;
  upload: (file: File) => Promise<{ url: string }>;
  onUploaded: (url: string) => void;
  blockedReason?: string | null;
}) {
  const inputRef = useRef<HTMLInputElement>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const blocked = blockedReason !== null;

  async function handle(file: File | undefined) {
    if (!file || busy || blocked) return;
    setError(null);
    setBusy(true);
    const result = await submitPhotoFile(file, upload);
    setBusy(false);
    if (result.ok) onUploaded(result.url);
    else setError(result.message);
    if (inputRef.current) inputRef.current.value = "";
  }

  return (
    <div className="grid gap-1">
      <div className="flex flex-wrap items-center gap-3">
        <Button
          type="button"
          variant="secondary"
          size="sm"
          disabled={busy || blocked}
          data-testid={`${testId}-button`}
          onClick={() => inputRef.current?.click()}
        >
          {busy ? "Uploading…" : buttonLabel}
        </Button>
        <span id={`${testId}-hint`} className="text-xs text-rally-muted">
          {blocked ? blockedReason : hint}
        </span>
        <input
          ref={inputRef}
          type="file"
          accept="image/png,image/jpeg"
          data-testid={`${testId}-file`}
          aria-label={label}
          aria-describedby={`${testId}-hint`}
          className="sr-only"
          disabled={busy || blocked}
          onChange={(event) => void handle(event.target.files?.[0])}
        />
      </div>
      {error && (
        <span role="alert" data-testid={`${testId}-error`} className="text-xs font-medium text-red-700">
          {error}
        </span>
      )}
    </div>
  );
}
