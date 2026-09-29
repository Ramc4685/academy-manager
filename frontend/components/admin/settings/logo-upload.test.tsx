import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it, vi } from "vitest";

import {
  LOGO_MAX_BYTES,
  LogoUpload,
  logoFileError,
  logoUploadErrorMessage,
  submitLogoFile,
} from "./logo-upload";

const png = (size = 1000) => new File([new Uint8Array(size)], "logo.png", { type: "image/png" });

describe("logoFileError", () => {
  it("accepts PNG and JPEG within the cap", () => {
    expect(logoFileError({ type: "image/png", size: 10 })).toBeNull();
    expect(logoFileError({ type: "image/jpeg", size: LOGO_MAX_BYTES })).toBeNull();
  });

  it("refuses other types and oversize files in plain words", () => {
    expect(logoFileError({ type: "image/gif", size: 10 })).toBe("Choose a PNG or JPG image.");
    expect(logoFileError({ type: "image/svg+xml", size: 10 })).toBe("Choose a PNG or JPG image.");
    expect(logoFileError({ type: "image/png", size: LOGO_MAX_BYTES + 1 })).toBe(
      "That image is over 2 MB. Choose a smaller one.",
    );
    expect(logoFileError({ type: "image/png", size: 0 })).toMatch(/empty/);
  });
});

describe("submitLogoFile", () => {
  it("returns the stored url", async () => {
    const upload = vi.fn(async () => ({ logo_url: "https://firebasestorage.googleapis.com/x" }));
    expect(await submitLogoFile(png(), upload)).toEqual({
      ok: true,
      url: "https://firebasestorage.googleapis.com/x",
    });
  });

  it("does not call the server for a file the pre-check refuses", async () => {
    const upload = vi.fn();
    const result = await submitLogoFile(new File(["x"], "a.gif", { type: "image/gif" }), upload);
    expect(result).toEqual({ ok: false, message: "Choose a PNG or JPG image." });
    expect(upload).not.toHaveBeenCalled();
  });

  it("shows the server's message for a 4xx and a generic one for a 5xx", async () => {
    const client = Object.assign(new Error("That file is not a PNG or JPG image."), { status: 422 });
    expect(await submitLogoFile(png(), async () => Promise.reject(client))).toEqual({
      ok: false,
      message: "That file is not a PNG or JPG image.",
    });
    const server = Object.assign(new Error("boom"), { status: 502 });
    const result = await submitLogoFile(png(), async () => Promise.reject(server));
    expect(result.ok).toBe(false);
    expect(logoUploadErrorMessage(server)).toMatch(/paste a link instead/);
    expect(logoUploadErrorMessage(new TypeError("network"))).toMatch(/Try again/);
  });
});

describe("LogoUpload markup", () => {
  it("offers choose-file and a png/jpg-only input, with the hint", () => {
    const html = renderToStaticMarkup(<LogoUpload upload={vi.fn()} onUploaded={vi.fn()} />);
    expect(html).toContain('data-testid="academy-logo-dropzone"');
    expect(html).toContain('accept="image/png,image/jpeg"');
    expect(html).toContain("Choose file");
    expect(html).toContain("PNG or JPG, up to 2 MB");
  });
});
