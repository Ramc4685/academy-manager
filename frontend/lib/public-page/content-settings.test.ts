import { describe, expect, it, vi } from "vitest";

import type { AdminPublicPageSettingsView } from "@/lib/api/admin";
import {
  GALLERY_MAX,
  HIGHLIGHTS_MAX,
  PHOTO_MAX_BYTES,
  addHighlight,
  coachRows,
  contentErrors,
  contentPayload,
  galleryUploadBlocker,
  moveItem,
  photoFileError,
  photoUploadErrorMessage,
  setCoachProfile,
  submitPhotoFile,
  toContentForm,
} from "./content-settings";

const view = (extra: Partial<AdminPublicPageSettingsView> = {}): AdminPublicPageSettingsView => ({
  published: true,
  show_price: true,
  show_availability: true,
  price_period_default: "month",
  trials_open: true,
  privacy_notice_url: null,
  public_url: null,
  ...extra,
});

describe("photoFileError", () => {
  it("accepts PNG and JPEG up to 5 MB", () => {
    expect(photoFileError({ type: "image/png", size: 10 })).toBeNull();
    expect(photoFileError({ type: "image/jpeg", size: PHOTO_MAX_BYTES })).toBeNull();
  });

  it("refuses other types, oversize and empty files in plain words", () => {
    expect(photoFileError({ type: "image/gif", size: 10 })).toBe("Choose a PNG or JPG image.");
    expect(photoFileError({ type: "image/png", size: PHOTO_MAX_BYTES + 1 })).toBe(
      "That image is over 5 MB. Choose a smaller one.",
    );
    expect(photoFileError({ type: "image/png", size: 0 })).toMatch(/empty/);
  });
});

describe("submitPhotoFile", () => {
  const jpg = (size = 100) => new File([new Uint8Array(size)], "a.jpg", { type: "image/jpeg" });

  it("returns the stored url", async () => {
    const upload = vi.fn(async () => ({ url: "https://cdn.example/x.jpg" }));
    expect(await submitPhotoFile(jpg(), upload)).toEqual({
      ok: true,
      url: "https://cdn.example/x.jpg",
    });
  });

  it("does not call the server for a file the pre-check refuses", async () => {
    const upload = vi.fn();
    const result = await submitPhotoFile(new File(["x"], "a.gif", { type: "image/gif" }), upload);
    expect(result.ok).toBe(false);
    expect(upload).not.toHaveBeenCalled();
  });

  it("shows the server's message for a 4xx and a generic one for a 5xx", async () => {
    const client = Object.assign(new Error("Confirm that parents agreed."), { status: 422 });
    expect(await submitPhotoFile(jpg(), () => Promise.reject(client))).toEqual({
      ok: false,
      message: "Confirm that parents agreed.",
    });
    expect(photoUploadErrorMessage(Object.assign(new Error("boom"), { status: 502 }))).toMatch(
      /Try again/,
    );
  });
});

describe("galleryUploadBlocker", () => {
  it("blocks the picker until the parents-agreed box is ticked", () => {
    expect(galleryUploadBlocker({ consent: false, count: 0 })).toBe("consent");
    expect(galleryUploadBlocker({ consent: true, count: 0 })).toBeNull();
  });

  it("blocks at the gallery cap even with consent", () => {
    expect(galleryUploadBlocker({ consent: true, count: GALLERY_MAX })).toBe("full");
    expect(galleryUploadBlocker({ consent: true, count: GALLERY_MAX - 1 })).toBeNull();
  });
});

describe("contentPayload", () => {
  it("sends nothing when nothing changed, and defaults are today's page", () => {
    const original = toContentForm(view());
    expect(original).toEqual({
      hero_photo_url: null,
      about_text: "",
      highlights: [],
      gallery: [],
      coach_profiles: [],
      faqs: [],
    });
    expect(contentPayload(original, toContentForm(view()))).toEqual({});
  });

  it("sends only the sections that changed", () => {
    const original = toContentForm(view({ about_text: "Hi", highlights: ["Small groups"] }));
    const form = { ...original, hero_photo_url: "https://cdn.example/h.jpg" };
    expect(contentPayload(original, form)).toEqual({ hero_photo_url: "https://cdn.example/h.jpg" });
    expect(contentPayload(original, { ...form, hero_photo_url: null })).toEqual({});
  });

  it("removing the hero photo sends null", () => {
    const original = toContentForm(view({ hero_photo_url: "https://cdn.example/h.jpg" }));
    expect(contentPayload(original, { ...original, hero_photo_url: null })).toEqual({
      hero_photo_url: null,
    });
  });

  it("trims text and drops blank highlights and empty FAQ rows", () => {
    const original = toContentForm(view());
    const payload = contentPayload(original, {
      ...original,
      about_text: "  Est. 2019  ",
      highlights: [" All levels ", "   "],
      faqs: [
        { question: " Cost? ", answer: " See classes. " },
        { question: "", answer: "" },
      ],
    });
    expect(payload).toEqual({
      about_text: "Est. 2019",
      highlights: ["All levels"],
      faqs: [{ question: "Cost?", answer: "See classes." }],
    });
  });

  it("clearing every FAQ sends an empty list (back to the standard questions)", () => {
    const original = toContentForm(view({ faqs: [{ question: "Q", answer: "A" }] }));
    expect(contentPayload(original, { ...original, faqs: [] })).toEqual({ faqs: [] });
  });

  it("always confirms consent on the gallery it sends", () => {
    const original = toContentForm(view());
    const payload = contentPayload(original, {
      ...original,
      gallery: [{ url: "https://cdn.example/g.jpg", caption: " Sat ", consent_confirmed: true }],
    });
    expect(payload.gallery).toEqual([
      { url: "https://cdn.example/g.jpg", caption: "Sat", consent_confirmed: true },
    ]);
  });

  it("does not send profiles of people no longer on the coach list", () => {
    const original = toContentForm(
      view({
        coach_profiles: [
          { coach_id: "gone", photo_url: null, bio: "old", shown: true },
          { coach_id: "c1", photo_url: null, bio: "", shown: true },
        ],
      }),
    );
    const form = {
      ...original,
      coach_profiles: original.coach_profiles.map((p) =>
        p.coach_id === "c1" ? { ...p, bio: "New bio" } : p,
      ),
    };
    const payload = contentPayload(original, form, new Set(["c1"]));
    expect(payload.coach_profiles).toEqual([
      { coach_id: "c1", photo_url: null, bio: "New bio", shown: true },
    ]);
  });
});

describe("contentErrors", () => {
  it("passes an empty form and flags half-filled FAQ rows", () => {
    const empty = toContentForm(view());
    expect(contentErrors(empty)).toEqual([]);
    expect(contentErrors({ ...empty, faqs: [{ question: "Q", answer: " " }] })).toHaveLength(1);
    expect(contentErrors({ ...empty, faqs: [{ question: "", answer: "" }] })).toEqual([]);
  });
});

describe("list editing", () => {
  it("moves items up and down and ignores moves off the ends", () => {
    expect(moveItem(["a", "b", "c"], 1, -1)).toEqual(["b", "a", "c"]);
    expect(moveItem(["a", "b", "c"], 1, 1)).toEqual(["a", "c", "b"]);
    expect(moveItem(["a", "b"], 0, -1)).toEqual(["a", "b"]);
    expect(moveItem(["a", "b"], 1, 1)).toEqual(["a", "b"]);
  });

  it("adds highlights up to six, ignoring blanks and duplicates", () => {
    expect(addHighlight([], "  ")).toEqual([]);
    expect(addHighlight(["Small groups"], "small groups")).toEqual(["Small groups"]);
    let list: string[] = [];
    for (let i = 0; i < HIGHLIGHTS_MAX + 2; i += 1) list = addHighlight(list, `h${i}`);
    expect(list).toHaveLength(HIGHLIGHTS_MAX);
  });

  it("builds one row per coach with its profile", () => {
    const rows = coachRows(
      [
        { user_id: "c1", display_name: "Alex" },
        { user_id: "c1", display_name: "Alex" },
        { user_id: "c2", display_name: "Sam" },
      ],
      [{ coach_id: "c2", photo_url: null, bio: "Hi", shown: true }],
    );
    expect(rows.map((r) => [r.coach_id, r.profile?.bio ?? null])).toEqual([
      ["c1", null],
      ["c2", "Hi"],
    ]);
  });

  it("creates, edits and removes a coach profile", () => {
    let profiles = setCoachProfile([], "c1", { bio: "L2 BWF" });
    expect(profiles).toEqual([{ coach_id: "c1", photo_url: null, bio: "L2 BWF", shown: true }]);
    profiles = setCoachProfile(profiles, "c1", { shown: false });
    expect(profiles[0]?.shown).toBe(false);
    profiles = setCoachProfile(profiles, "c1", { bio: "" });
    expect(profiles).toEqual([]);
    expect(setCoachProfile([], "c1", { shown: false })).toEqual([]);
  });

  it("caps a bio at 280 characters", () => {
    const [profile] = setCoachProfile([], "c1", { bio: "x".repeat(400) });
    expect(profile?.bio).toHaveLength(280);
  });
});
