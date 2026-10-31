/**
 * TypeScript mirror of the anonymous public page DTOs served by
 * `GET /api/v2/public/academy` (backend/v2/interfaces/public/dtos.py).
 *
 * Plain shapes only. Colours arrive pre-computed (`brand_fill`,
 * `brand_on_color` come from backend/v2/shared/comms/colour.py
 * `readable_button_colors`); nothing here derives a colour.
 */

export type PublicPricePeriod = "month" | "class" | "term";
export type PublicSeatBand = "open" | "few" | "waitlist";

export interface PublicAgeBand {
  min_age: number | null;
  max_age: number | null;
}

export interface PublicPrice {
  amount_cents: number;
  period: PublicPricePeriod | string;
}

export interface PublicSeats {
  band: PublicSeatBand | string;
  seats_left: number | null;
}

export interface PublicClass {
  public_id: string;
  title: string;
  description: string | null;
  level: string | null;
  age_band: PublicAgeBand | null;
  days_of_week: string[];
  start_time: string | null;
  end_time: string | null;
  timezone: string | null;
  /** Date of a one-off class (YYYY-MM-DD); null for a weekly class. */
  starts_on: string | null;
  location: string | null;
  venue_address: string | null;
  /** Already resolved server-side from the class's coach display setting. */
  coach_name: string | null;
  /** Null when the academy hides prices or the class has no price. */
  price: PublicPrice | null;
  /** Null when the academy hides availability. */
  seats: PublicSeats | null;
}

export interface PublicProgram {
  public_id: string;
  name: string;
  description: string | null;
  level: string | null;
  age_band: PublicAgeBand | null;
  classes: PublicClass[];
}

export interface PublicBrand {
  name: string;
  logo_url: string | null;
  brand_color: string | null;
  brand_fill: string;
  brand_on_color: string;
}

export interface PublicVenue {
  address: string | null;
  hours_text: string | null;
}

export interface PublicAcademy extends PublicBrand {
  venue: PublicVenue;
  timezone: string | null;
  currency: string;
  /** The academy's support email only; null when it has not set one. No
   * phone number is ever exposed here (owner decision). */
  support_email: string | null;
}

export interface PublicPageFlags {
  trials_open: boolean;
  show_price: boolean;
  show_availability: boolean;
  price_period_default: PublicPricePeriod | string;
  privacy_notice_url: string | null;
  /** The academy's chosen look; absent reads as "floodlit" (today's page). */
  theme?: "floodlit" | "daylight" | "showcase" | string;
  /** Classes show "Only N seats left" at or below this (0 never). Absent: 3. */
  seats_left_threshold?: number;
  /** Footer links the academy set in Academy profile > Legal links. */
  terms_url?: string | null;
  refund_policy_url?: string | null;
}

export interface PublicGalleryPhoto {
  url: string;
  caption: string;
}

export interface PublicCoachProfile {
  name: string;
  photo_url: string | null;
  bio: string;
}

export interface PublicFaq {
  question: string;
  answer: string;
}

export interface PublicAcademyPage {
  state: "published";
  academy: PublicAcademy;
  page: PublicPageFlags;
  programs: PublicProgram[];
  ungrouped_classes: PublicClass[];
  /* Academy content. Every field is optional: an academy that has written
   * nothing renders exactly the original page. */
  hero_photo_url?: string | null;
  about_text?: string;
  highlights?: string[];
  gallery?: PublicGalleryPhoto[];
  /** Coaches with a profile; a class coach with none stays a name only. */
  coaches?: PublicCoachProfile[];
  /** Empty or absent: the built-in FAQ list. */
  faqs?: PublicFaq[];
}

export interface PublicAcademyNotPublished {
  state: "not_published";
  academy: PublicBrand;
}

/**
 * What the root route renders for this request.
 *
 * - `platform`: the product's own host; render the CourtMastr landing page.
 * - `published` / `not_published`: the tenant page in one of its shapes.
 * - `unknown_host`: the backend's identical 404 (no, foreign, suspended or
 *   cancelled tenant); the page calls `notFound()`.
 * - `unavailable`: the API failed or answered something unexpected.
 */
export type PublicPageResult =
  | { kind: "platform" }
  | { kind: "published"; page: PublicAcademyPage }
  | { kind: "not_published"; page: PublicAcademyNotPublished }
  | { kind: "unknown_host" }
  | { kind: "unavailable" };
