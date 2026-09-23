/**
 * Pure logic behind the admin "Public page" settings panel (Lane B5).
 *
 * Kept out of the component so vitest (node environment) can pin the rules:
 * which keys a Save sends, which privacy links are accepted before the
 * server sees them, where "View page" points, and which classes the per-class
 * list shows.
 */

import type {
  AdminClassPublicProfileView,
  AdminProgramView,
  AdminPublicPageSettingsView,
  PublicCoachDisplay,
  PublicPricePeriod,
  UpdateAdminPublicPageSettingsRequest,
} from "@/lib/api/admin";
import { isPlatformProductHost } from "@/lib/public-page/host";

export const PRICE_PERIOD_LABEL: Record<PublicPricePeriod, string> = {
  month: "Per month",
  class: "Per class",
  term: "Per term",
};

export const COACH_DISPLAY_LABEL: Record<PublicCoachDisplay, string> = {
  full_name: "Full name",
  first_name: "First name only",
  hidden: "Hidden",
};

export interface PublicPageForm {
  published: boolean;
  show_price: boolean;
  show_availability: boolean;
  price_period_default: PublicPricePeriod;
  trials_open: boolean;
  /** Text box value; blank means "no privacy link". */
  privacy_notice_url: string;
}

/** Form state from the server view; the domain defaults when nothing loaded yet. */
export function toPublicPageForm(
  view: AdminPublicPageSettingsView | null | undefined
): PublicPageForm {
  return {
    published: view?.published ?? false,
    show_price: view?.show_price ?? true,
    show_availability: view?.show_availability ?? true,
    price_period_default: view?.price_period_default ?? "month",
    trials_open: view?.trials_open ?? true,
    privacy_notice_url: view?.privacy_notice_url ?? "",
  };
}

/** Only the keys that changed, so saving one switch can never reset another. */
export function publicPagePayload(
  original: PublicPageForm,
  form: PublicPageForm
): UpdateAdminPublicPageSettingsRequest {
  const payload: UpdateAdminPublicPageSettingsRequest = {};
  if (form.published !== original.published) payload.published = form.published;
  if (form.show_price !== original.show_price) payload.show_price = form.show_price;
  if (form.show_availability !== original.show_availability) {
    payload.show_availability = form.show_availability;
  }
  if (form.price_period_default !== original.price_period_default) {
    payload.price_period_default = form.price_period_default;
  }
  if (form.trials_open !== original.trials_open) payload.trials_open = form.trials_open;
  const url = form.privacy_notice_url.trim();
  if (url !== original.privacy_notice_url.trim()) payload.privacy_notice_url = url || null;
  return payload;
}

/**
 * The privacy link is rendered as an href on a public page. The server only
 * accepts http(s); this mirrors it so the Save button can say why up front.
 */
export function privacyUrlError(value: string): string | null {
  const trimmed = value.trim();
  if (!trimmed) return null;
  let parsed: URL;
  try {
    parsed = new URL(trimmed);
  } catch {
    return "Enter a full web address starting with https://";
  }
  if (parsed.protocol !== "https:" && parsed.protocol !== "http:") {
    return "Only http:// or https:// links are allowed.";
  }
  if (!parsed.hostname) return "Enter a full web address starting with https://";
  return null;
}

/**
 * Where "View page" points. The academy's own domain when the server knows
 * it; otherwise the current origin, but only when this is not a CourtMastr
 * product host (there `/` is the product landing page, not the academy's).
 * `null` means "no address yet": the panel says so rather than guessing.
 */
export function viewPageHref(
  publicUrl: string | null | undefined,
  location: { origin: string; host: string } | null
): string | null {
  if (publicUrl) return publicUrl;
  if (!location || !location.host) return null;
  if (isPlatformProductHost(location.host, {})) return null;
  return `${location.origin}/`;
}

/**
 * The classes the per-class list shows: every live class, plus any ended or
 * cancelled one still switched on (so it can be switched off). Sorted by
 * title so the list is stable between saves.
 */
export function listableClasses(
  classes: ReadonlyArray<AdminClassPublicProfileView>
): AdminClassPublicProfileView[] {
  return classes
    .filter(
      (row) => row.published || (row.status !== "cancelled" && row.status !== "completed")
    )
    .slice()
    .sort((a, b) =>
      (a.title ?? a.session_id).localeCompare(b.title ?? b.session_id, undefined, {
        sensitivity: "base",
      })
    );
}

export interface ProgramOption {
  value: string;
  label: string;
}

/**
 * The program choices for one class row: every active program, plus the
 * class's current program when it is archived (or no longer listed at all),
 * so a class in an archived program never reads as "No program". Archiving
 * a program keeps the class's program_id on the server.
 */
export function programOptions(
  programs: ReadonlyArray<AdminProgramView>,
  currentProgramId: string | null
): ProgramOption[] {
  const options: ProgramOption[] = programs
    .filter((program) => !program.archived)
    .map((program) => ({ value: program.program_id, label: program.name }));
  if (currentProgramId !== null && !options.some((o) => o.value === currentProgramId)) {
    const current = programs.find((program) => program.program_id === currentProgramId);
    options.push({
      value: currentProgramId,
      label: current ? `${current.name} (archived)` : "Unknown program",
    });
  }
  return options;
}
