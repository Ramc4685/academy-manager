/**
 * Pure logic behind the admin "Photos & details" card (Settings overhaul
 * Phase 6, content lane).
 *
 * Kept out of the component so vitest (node environment) can pin the rules:
 * the limits mirrored from the server, which upload the consent box gates,
 * which keys a Save sends, and how coach and FAQ rows are edited.
 */

import type {
  AdminCoachProfile,
  AdminFaq,
  AdminGalleryPhoto,
  AdminPublicPageSettingsView,
  UpdateAdminPublicPageSettingsRequest,
} from "@/lib/api/admin";
import type { ApiError } from "@/lib/api/client";

/** Mirrors backend/v2/contexts/identity/domain/public_page.py. */
export const ABOUT_MAX = 1200;
export const HIGHLIGHTS_MAX = 6;
export const HIGHLIGHT_MAX_CHARS = 60;
export const GALLERY_MAX = 12;
export const CAPTION_MAX = 120;
export const BIO_MAX = 280;
export const FAQS_MAX = 12;
export const FAQ_QUESTION_MAX = 160;
export const FAQ_ANSWER_MAX = 800;

/** Mirrors the backend cap for hero, gallery and coach photos. */
export const PHOTO_MAX_BYTES = 5 * 1024 * 1024;
const PHOTO_TYPES = ["image/png", "image/jpeg"];

export const GALLERY_CONSENT_LABEL =
  "Parents or guardians of any children shown agreed to this photo being published";

/** Plain-language pre-check; the server still decides from the file's contents. */
export function photoFileError(file: { type: string; size: number }): string | null {
  if (!PHOTO_TYPES.includes(file.type)) return "Choose a PNG or JPG image.";
  if (file.size > PHOTO_MAX_BYTES) return "That image is over 5 MB. Choose a smaller one.";
  if (file.size === 0) return "That file is empty. Choose a PNG or JPG image.";
  return null;
}

/** The server's own words for a 4xx, a generic line otherwise. */
export function photoUploadErrorMessage(error: unknown): string {
  const err = error as Partial<ApiError> | null;
  if (err && typeof err.status === "number" && err.status < 500 && err.message) {
    return err.message;
  }
  return "We could not upload that photo. Try again in a moment.";
}

export type PhotoUploadResult = { ok: true; url: string } | { ok: false; message: string };

/** Validate, upload and report; never throws. */
export async function submitPhotoFile(
  file: File,
  upload: (file: File) => Promise<{ url: string }>,
): Promise<PhotoUploadResult> {
  const problem = photoFileError(file);
  if (problem) return { ok: false, message: problem };
  try {
    const result = await upload(file);
    return { ok: true, url: result.url };
  } catch (error) {
    return { ok: false, message: photoUploadErrorMessage(error) };
  }
}

/**
 * Whether the gallery file picker may open. A gallery photo may show
 * children, so the "parents agreed" box must be ticked first, and the
 * gallery must have room.
 */
export function galleryUploadBlocker(state: {
  consent: boolean;
  count: number;
}): "consent" | "full" | null {
  if (state.count >= GALLERY_MAX) return "full";
  if (!state.consent) return "consent";
  return null;
}

export interface ContentForm {
  hero_photo_url: string | null;
  about_text: string;
  highlights: string[];
  gallery: AdminGalleryPhoto[];
  coach_profiles: AdminCoachProfile[];
  faqs: AdminFaq[];
}

export function toContentForm(
  view: AdminPublicPageSettingsView | null | undefined,
): ContentForm {
  return {
    hero_photo_url: view?.hero_photo_url ?? null,
    about_text: view?.about_text ?? "",
    highlights: [...(view?.highlights ?? [])],
    gallery: (view?.gallery ?? []).map((photo) => ({ ...photo })),
    coach_profiles: (view?.coach_profiles ?? []).map((profile) => ({ ...profile })),
    faqs: (view?.faqs ?? []).map((faq) => ({ ...faq })),
  };
}

/** What Save would send for each list: blanks dropped, text trimmed. */
function normalizeHighlights(list: string[]): string[] {
  return list.map((item) => item.trim()).filter(Boolean);
}

function normalizeFaqs(list: AdminFaq[]): AdminFaq[] {
  return list
    .map((faq) => ({ question: faq.question.trim(), answer: faq.answer.trim() }))
    .filter((faq) => faq.question !== "" || faq.answer !== "");
}

function normalizeCoaches(
  list: AdminCoachProfile[],
  knownCoachIds: ReadonlySet<string> | null,
): AdminCoachProfile[] {
  return list
    .filter((profile) => !knownCoachIds || knownCoachIds.has(profile.coach_id))
    .map((profile) => ({ ...profile, bio: profile.bio.trim() }));
}

function same(a: unknown, b: unknown): boolean {
  return JSON.stringify(a) === JSON.stringify(b);
}

/**
 * Only the keys that changed, so saving one section can never reset another.
 * `knownCoachIds` drops profiles of people no longer on the coach list (the
 * server would refuse them).
 */
export function contentPayload(
  original: ContentForm,
  form: ContentForm,
  knownCoachIds: ReadonlySet<string> | null = null,
): UpdateAdminPublicPageSettingsRequest {
  const payload: UpdateAdminPublicPageSettingsRequest = {};
  if (form.hero_photo_url !== original.hero_photo_url) {
    payload.hero_photo_url = form.hero_photo_url;
  }
  if (form.about_text.trim() !== original.about_text.trim()) {
    payload.about_text = form.about_text.trim();
  }
  const highlights = normalizeHighlights(form.highlights);
  if (!same(highlights, normalizeHighlights(original.highlights))) payload.highlights = highlights;
  if (!same(form.gallery, original.gallery)) {
    payload.gallery = form.gallery.map((photo) => ({
      url: photo.url,
      caption: photo.caption.trim(),
      consent_confirmed: true,
    }));
  }
  const coaches = normalizeCoaches(form.coach_profiles, knownCoachIds);
  if (!same(coaches, normalizeCoaches(original.coach_profiles, knownCoachIds))) {
    payload.coach_profiles = coaches;
  }
  const faqs = normalizeFaqs(form.faqs);
  if (!same(faqs, normalizeFaqs(original.faqs))) payload.faqs = faqs;
  return payload;
}

/** Problems that block Save, in plain words. Empty when the form can be sent. */
export function contentErrors(form: ContentForm): string[] {
  const errors: string[] = [];
  if (form.about_text.length > ABOUT_MAX) {
    errors.push(`About us is over ${ABOUT_MAX} characters.`);
  }
  if (normalizeHighlights(form.highlights).length > HIGHLIGHTS_MAX) {
    errors.push(`Use up to ${HIGHLIGHTS_MAX} highlights.`);
  }
  if (form.faqs.some((faq) => (faq.question.trim() === "") !== (faq.answer.trim() === ""))) {
    errors.push("Each question needs an answer, and each answer needs a question.");
  }
  return errors;
}

// --- list editing ------------------------------------------------------

/** Move one item up (-1) or down (+1); out-of-range moves change nothing. */
export function moveItem<T>(list: readonly T[], index: number, delta: -1 | 1): T[] {
  const target = index + delta;
  if (index < 0 || index >= list.length || target < 0 || target >= list.length) {
    return [...list];
  }
  const next = [...list];
  const [item] = next.splice(index, 1);
  next.splice(target, 0, item as T);
  return next;
}

/** Add a highlight; ignores blanks and duplicates and stops at the cap. */
export function addHighlight(list: readonly string[], raw: string): string[] {
  const value = raw.trim().slice(0, HIGHLIGHT_MAX_CHARS);
  if (!value || list.length >= HIGHLIGHTS_MAX) return [...list];
  if (list.some((item) => item.toLowerCase() === value.toLowerCase())) return [...list];
  return [...list, value];
}

export interface CoachRowSource {
  user_id: string;
  display_name: string;
}

export interface CoachRow {
  coach_id: string;
  name: string;
  profile: AdminCoachProfile | null;
}

/** One row per academy coach, each with its profile when it has one. */
export function coachRows(
  coaches: ReadonlyArray<CoachRowSource>,
  profiles: ReadonlyArray<AdminCoachProfile>,
): CoachRow[] {
  const byId = new Map(profiles.map((profile) => [profile.coach_id, profile]));
  const seen = new Set<string>();
  const rows: CoachRow[] = [];
  for (const coach of coaches) {
    if (seen.has(coach.user_id)) continue;
    seen.add(coach.user_id);
    rows.push({
      coach_id: coach.user_id,
      name: coach.display_name || "Coach",
      profile: byId.get(coach.user_id) ?? null,
    });
  }
  return rows;
}

/**
 * Apply an edit to one coach's profile. A coach with no photo, no bio and
 * "shown" off has no profile at all (they stay a plain name on the page).
 * Adding a photo or bio to a coach with no profile turns "shown" on.
 */
export function setCoachProfile(
  profiles: ReadonlyArray<AdminCoachProfile>,
  coachId: string,
  patch: Partial<Omit<AdminCoachProfile, "coach_id">>,
): AdminCoachProfile[] {
  const existing = profiles.find((profile) => profile.coach_id === coachId);
  const base: AdminCoachProfile = existing ?? {
    coach_id: coachId,
    photo_url: null,
    bio: "",
    shown: true,
  };
  const next: AdminCoachProfile = {
    ...base,
    ...patch,
    bio: (patch.bio ?? base.bio).slice(0, BIO_MAX),
  };
  const empty = next.photo_url === null && next.bio.trim() === "" && !next.shown;
  if (!existing) return empty ? [...profiles] : [...profiles, next];
  // Keep the profile where it was so undoing an edit is not a change.
  return empty
    ? profiles.filter((profile) => profile.coach_id !== coachId)
    : profiles.map((profile) => (profile.coach_id === coachId ? next : profile));
}

/** Turning "shown" on for a coach with no profile creates an empty shown one. */
export function isCoachShown(profile: AdminCoachProfile | null): boolean {
  return profile?.shown ?? false;
}
