# Website Embeds, Calendar Sync, Accounting Export, Public API — Requirements

Date: 2026-07-06 · Roadmap item 9 of 9 · [Index](2026-07-06-00-roadmap-index.md)

## Problem

This is the "ecosystem surface" gap identified in the competitive analysis: four
related but distinct capabilities that let an academy's existing tools talk to us
instead of us being a closed island. Jackrabbit ships a drop-in JS widget plus a
WordPress plugin for class-list/registration embedding; Sawyer has a similar
(if buggy) embeddable widget; TeamUp includes a free, documented REST API and
markets it directly; Amilia's API earns explicit developer praise
("very easy to integrate... fairly robust documentation"); QuickBooks/Xero export
via Zapier is the category-wide accounting-integration norm (nobody has deep
native accounting, but everybody has *some* export path). We have none of the
four: no embeddable widgets, no calendar feed, no accounting export, no public API.

This doc bundles four related-but-separable capabilities because they share an
underlying need (a stable, documented, external-facing read surface over our
domain data) — but they can and should ship independently; see Requirements for
per-capability scoping.

## Current State (codebase evidence)

- Frontend calendar view exists in-app (`FullCalendar` React component,
  `/frontend/app/(shared)/calendar`) but has no external export/subscribe surface —
  no iCal (.ics) feed endpoint exists anywhere in `backend/v2/interfaces/`.
- No website-embeddable widget (class list, registration form) exists — the
  parent-facing enrollment flow lives entirely inside our own authenticated app,
  with no public/embeddable read-only or lightweight-registration surface for an
  academy's own marketing website.
- No accounting integration exists — no QuickBooks/Xero connector, no CSV export
  formatted for accounting import. Admin billing views expose data on-screen only.
- No public API exists — all `backend/v2/interfaces/*` routes are BFF-shaped
  (persona-specific, session-authenticated) rather than a documented, stable,
  external-developer-facing API surface. Building a public API is a materially
  larger effort than the other three items in this doc (needs its own auth model,
  e.g., API keys/OAuth, rate limiting, versioning, and documentation) — treat it
  as the largest sub-item, not a quick add-on.

## Goals (per capability — evaluate and sequence independently)

### A. Website embed widgets
- Let an academy embed a read-only class list and/or a lightweight registration
  form on their own external marketing website (WordPress, Squarespace, custom
  site), matching the Jackrabbit/Sawyer/Amilia pattern.

### B. Calendar sync (iCal)
- Let a parent or coach subscribe to a personal calendar feed (read-only .ics)
  reflecting their upcoming sessions, importable into Google Calendar/Apple
  Calendar/Outlook. Start with read-only export — do NOT attempt two-way sync
  (Omnify's Google Calendar sync caused double-booking bugs that reportedly lost
  them customers; a one-way feed avoids that entire failure class).

### C. Accounting export
- Let an admin export invoices/payments/fees in a format importable into
  QuickBooks Online (the category-wide standard target) — either a native
  connector or, at minimum, a correctly-formatted CSV export matching QBO's
  import schema. A Zapier-based integration (matching how Amilia/TeamUp/Omnify
  all do it) is an acceptable, lower-effort alternative to a native connector.

### D. Public API
- Expose a documented, versioned, authenticated (API key or OAuth) read API over
  core domain data (students, enrollments, sessions, invoices) for academies that
  want to build their own integrations or connect third-party tools (Zapier,
  custom scripts). Write operations, if any, should be scoped narrowly and later
  — start read-only.

## Non-Goals

- Not building a two-way calendar sync (see B) — one-way export only.
- Not building a full accounting *system* — export/integration only, we remain
  the source of truth for billing.
- Not opening the public API to write-heavy operations (enrollment creation,
  payment initiation) in the first release — read-only reduces both security
  surface and support burden while the API's real-world usage patterns are still
  unknown.

## Requirements

### R1 (A — Embeds). Embeddable widget
- A `<script>`-tag-based embed (matching Jackrabbit's model) renders a read-only,
  branded class list for a given academy, pulling from existing session/program
  data via a new lightweight, publicly-cacheable (no parent auth required) read
  endpoint scoped to public-safe fields only (class name, schedule, level — no
  student PII).
- Optionally, the embed can deep-link into the existing parent-facing
  registration/application flow rather than reimplementing registration inside
  the embed itself (smaller surface, reuses existing `StartApplication` flow).

### R2 (B — Calendar). iCal feed
- New endpoint generates a per-user (parent or coach), token-authenticated .ics
  feed URL (not requiring full session login to refresh in an external calendar
  app) reflecting that user's upcoming session occurrences.
- Feed token is revocable/regeneratable (if a parent's calendar URL leaks, they
  can invalidate it without changing their account password).

### R3 (C — Accounting). Export
- Admin can trigger an export (CSV at minimum, native QBO connector as a stretch
  goal) of invoices/payments/fees for a selected date range, in a schema mapped
  to QuickBooks Online's import format (or via a documented Zapier trigger/action
  pair, matching Amilia/TeamUp's approach, if a native connector is deprioritized).

### R4 (D — Public API). Read API
- New API-key-authenticated (per academy) versioned endpoint set
  (`/api/public/v1/...`) exposing read access to students, enrollments, sessions,
  and invoices, scoped to the requesting academy's tenant only (reuse existing
  tenant-isolation middleware, just with API-key auth instead of Firebase session
  auth).
- Rate limiting and per-key usage visibility (admin can see their own API key's
  request volume, at minimum for abuse/debugging purposes).
- Published API documentation (even a simple static reference) — an
  undocumented API is not meaningfully different from having none, per the
  competitive research's observation that Amilia's documented API is a specific,
  named source of developer praise.

## Data Model Changes

### New `public_embed_configs` (per academy, for A)
```text
academy_id
enabled: bool
theme_overrides: { colors, logo_url }   # matches Omnify's highest-rated feature
allowed_program_ids: [program_id] | null   # null = all public programs
```

### New `calendar_feed_tokens` (for B)
```text
token
user_id (parent_id or coach_id)
academy_id
created_at
revoked_at: datetime | null
```

### New `accounting_export_jobs` (for C)
```text
job_id
academy_id
requested_by: admin_user_id
date_range_start / date_range_end
format: "csv_qbo" | "zapier_trigger"
status: "pending" | "completed" | "failed"
file_artifact_id: string | null
```

### New `api_keys` (for D)
```text
key_id
academy_id
key_hash          # never store raw key
label
scopes: [string]  # e.g., "students:read", "invoices:read"
created_by: admin_user_id
created_at
revoked_at: datetime | null
last_used_at: datetime | null
rate_limit_per_minute: int
```

## Dependencies

- Best sequenced after the billing items (roadmap 1-4) settle their invoice-line
  schema, since accounting export (C) and the public API's invoice endpoints (D)
  need a stable schema to map against — building the export/API against a
  schema that's still actively changing means rework.
- A, B, and C are independently shippable in any order relative to each other; D
  (public API) is the largest effort and should be scoped as its own project once
  the business decides it's worth the ongoing maintenance/support commitment a
  public API implies (versioning, backward compatibility, external developer
  support).

## Open Decisions

1. Is a public API (D) actually a near-term priority, or is it the right item to
   defer entirely and revisit only if/when customers explicitly ask for Zapier/
   custom integrations? (Given its size relative to A/B/C, this deserves an
   explicit go/no-go rather than being bundled by default.)
2. Native QuickBooks Online connector vs. CSV export vs. Zapier integration for
   (C) — effort/value tradeoff needs a business call; Zapier is the fastest to
   ship and matches what every studied competitor actually does.
3. Should the embeddable widget (A) support full in-widget registration/checkout,
   or only class-list display with a deep-link to our own hosted registration
   flow? (Recommendation: deep-link only for v1 — full in-widget checkout is a
   much larger, riskier surface to secure and maintain.)
4. API key scoping granularity for (D): per-resource-type scopes (as sketched
   above) or all-or-nothing per key?

## Acceptance Criteria / Test Cases

- An embed script on an external test page renders a correct, publicly-safe class
  list for a given academy, with no student PII exposed.
- A parent's iCal feed URL, added to an external calendar app, correctly reflects
  their upcoming sessions and updates on subsequent refreshes (read-only, no
  write-back).
- Revoking a calendar feed token invalidates the old URL without requiring a
  password change.
- An accounting export for a given date range produces a file that imports
  cleanly into QuickBooks Online (or a working Zapier trigger fires with correct
  data), with tuition, fee, and discount lines all correctly categorized.
- A public API key scoped to `invoices:read` can list invoices for its own
  academy only, and cannot access another academy's data (tenant isolation holds
  under API-key auth, not just session auth).
- Rate limiting on the public API returns a clear, standard error (e.g., HTTP 429)
  once a key exceeds its configured limit, rather than degrading silently.
