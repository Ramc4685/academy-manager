"use client";

import { useRef, useState, type DragEvent } from "react";

import type { ApiError } from "@/lib/api/client";
import { Button } from "@/components/ds/button";

/** Mirrors the backend cap (POST /admin/academy/media). */
export const LOGO_MAX_BYTES = 2 * 1024 * 1024;
const LOGO_TYPES = ["image/png", "image/jpeg"];

/**
 * Plain-language pre-check so an obviously wrong file never leaves the
 * browser. The server still decides from the file's real contents.
 */
export function logoFileError(file: { type: string; size: number }): string | null {
  if (!LOGO_TYPES.includes(file.type)) return "Choose a PNG or JPG image.";
  if (file.size > LOGO_MAX_BYTES) return "That image is over 2 MB. Choose a smaller one.";
  if (file.size === 0) return "That file is empty. Choose a PNG or JPG image.";
  return null;
}

/** Message for a failed upload: the server's own words for 4xx, generic otherwise. */
export function logoUploadErrorMessage(error: unknown): string {
  const err = error as Partial<ApiError> | null;
  if (err && typeof err.status === "number" && err.status < 500 && err.message) {
    return err.message;
  }
  return "We could not upload that image. Try again, or paste a link instead.";
}

export type LogoUploadResult = { ok: true; url: string } | { ok: false; message: string };

/** Validate, upload and report; never throws. */
export async function submitLogoFile(
  file: File,
  upload: (file: File) => Promise<{ logo_url: string }>,
): Promise<LogoUploadResult> {
  const problem = logoFileError(file);
  if (problem) return { ok: false, message: problem };
  try {
    const result = await upload(file);
    return { ok: true, url: result.logo_url };
  } catch (error) {
    return { ok: false, message: logoUploadErrorMessage(error) };
  }
}

/**
 * Upload control for the Brand card: choose a file or drop one on it. It only
 * reports the new URL; saving still goes through the panel's Save button.
 */
export function LogoUpload({
  upload,
  onUploaded,
}: {
  upload: (file: File) => Promise<{ logo_url: string }>;
  onUploaded: (url: string) => void;
}) {
  const inputRef = useRef<HTMLInputElement>(null);
  const [busy, setBusy] = useState(false);
  const [dragging, setDragging] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [done, setDone] = useState(false);

  async function handle(file: File | undefined) {
    if (!file || busy) return;
    setError(null);
    setDone(false);
    setBusy(true);
    const result = await submitLogoFile(file, upload);
    setBusy(false);
    if (result.ok) {
      onUploaded(result.url);
      setDone(true);
    } else {
      setError(result.message);
    }
    if (inputRef.current) inputRef.current.value = "";
  }

  function onDrop(event: DragEvent<HTMLDivElement>) {
    event.preventDefault();
    setDragging(false);
    void handle(event.dataTransfer.files?.[0]);
  }

  return (
    <div className="grid gap-1.5 text-sm font-medium text-rally-ink">
      <span id="academy-logo-upload-label">Upload logo</span>
      <div
        data-testid="academy-logo-dropzone"
        onDragOver={(event) => {
          event.preventDefault();
          setDragging(true);
        }}
        onDragLeave={() => setDragging(false)}
        onDrop={onDrop}
        className={`flex flex-wrap items-center gap-3 rounded-md border border-dashed px-3 py-3 ${
          dragging ? "border-blue-500 bg-blue-50" : "border-rally-line bg-rally-paper"
        }`}
      >
        <Button
          type="button"
          variant="secondary"
          disabled={busy}
          onClick={() => inputRef.current?.click()}
        >
          {busy ? "Uploading…" : "Choose file"}
        </Button>
        <span id="academy-logo-upload-hint" className="text-xs font-normal text-rally-muted">
          PNG or JPG, up to 2 MB. Drag it here, or paste a link below.
        </span>
        <input
          ref={inputRef}
          type="file"
          accept="image/png,image/jpeg"
          data-testid="academy-logo-file"
          aria-labelledby="academy-logo-upload-label"
          aria-describedby="academy-logo-upload-hint"
          className="sr-only"
          disabled={busy}
          onChange={(event) => void handle(event.target.files?.[0])}
        />
      </div>
      {done && !error && (
        <span role="status" className="text-xs font-normal text-rally-muted">
          Uploaded. Save to use this logo.
        </span>
      )}
      {error && (
        <span role="alert" data-testid="academy-logo-error" className="text-xs font-medium text-red-700">
          {error}
        </span>
      )}
    </div>
  );
}
