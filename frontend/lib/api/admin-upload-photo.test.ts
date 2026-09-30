import { beforeEach, describe, expect, it, vi } from "vitest";

import { uploadAdminAcademyLogo, uploadAdminAcademyPhoto } from "./admin";
import * as client from "./client";

function sentBody(spy: ReturnType<typeof vi.spyOn>): FormData {
  return (spy.mock.calls[0]?.[1] as { body: FormData }).body;
}

describe("landing-page photo uploads", () => {
  beforeEach(() => vi.restoreAllMocks());
  const file = new File(["x"], "a.jpg", { type: "image/jpeg" });

  it("posts the purpose and, for the gallery, the consent flag", async () => {
    const spy = vi.spyOn(client, "apiFetch").mockResolvedValue({ url: "u" } as never);

    await uploadAdminAcademyPhoto(file, "gallery", { consent: true });

    expect(spy.mock.calls[0]?.[0]).toBe("/admin/academy/media");
    const body = sentBody(spy);
    expect(body.get("purpose")).toBe("gallery");
    expect(body.get("consent")).toBe("true");
    expect(body.get("file")).toBeInstanceOf(File);
  });

  it("sends no consent field unless asked", async () => {
    const spy = vi.spyOn(client, "apiFetch").mockResolvedValue({ url: "u" } as never);
    await uploadAdminAcademyPhoto(file, "hero");
    expect(sentBody(spy).get("consent")).toBeNull();
    expect(sentBody(spy).get("purpose")).toBe("hero");
  });

  it("keeps the logo upload purpose-free (server default)", async () => {
    const spy = vi.spyOn(client, "apiFetch").mockResolvedValue({ logo_url: "u" } as never);
    await uploadAdminAcademyLogo(file);
    expect(sentBody(spy).get("purpose")).toBeNull();
  });
});
