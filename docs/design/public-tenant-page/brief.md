# Public academy class page: design brief

Status: design stage, 2026-09-20. No application code changed. Prototype: `docs/design/public-tenant-page/prototype.html`.
All sample data is fictional ("Riverside Badminton", "Baseline Tennis Club"). The real tenant must never appear on this surface as showcase material (PRODUCT.md).

Owner answers captured this session (structured question round):

| Question | Answer |
|---|---|
| Primary action for a stranger | **Book a free trial.** Register is secondary, per class. |
| Whose brand the page wears | **Academy-led.** Rally supplies structure; CourtMastr is a small footer credit. |
| Price and open seats | **Both on by default, tenant can hide either.** Seats shown as bands, not exact counts. |
| Academy page address | **`<slug>-academy.courtmastr.com`** (one label under `courtmastr.com`, matching the production-ready tenant host). `academy.courtmastr.com` stays the product's own host. |
| Phase 1 trial action | Owner delegated ("do what is better"). **Decision: ship the real form in phase 1, no `mailto:` stopgap.** Reasoning in section 6. |
| Where public leads land | **People CRM.** The form writes the CRM's own lead record (`crm_contacts`), not the parent trial-requests queue. |
| What a price means | **Per month by default; each tenant can change it** (month, class or term). |
| Program grouping | **Yes, a real program entity** (name, level, ages, description, order). |
| Existing classes at launch | **Private until the owner switches each one on.** |
| Coach names | **Industry standard:** the coach's public display name in full, optional photo and one-line bio, academy can hide the coach column, each coach can be excluded. |
| Image storage | **Nothing exists, so build it** on the Firebase project's existing storage bucket (section 6, piece G). |
| CourtMastr footer credit | **Always on, not removable** for now (section 9 explains why this was asked). |

Impeccable mode for this surface: **Persuade** (the visitor decides and acts). This is the first Persuade surface in a product whose other surfaces are Operate, so it is allowed more expression than the app, inside the Rally system.

---

## 1. Job and audience

**Who arrives.** A parent who has never heard of the academy. On a phone, one-handed, often in a WhatsApp or Instagram in-app browser, from a Google search ("badminton classes near me"), a shared link, or a QR code on a poster at the hall. They are comparing two or three options and will give this page well under a minute.

**What they must learn, in order** (the page answers these top to bottom):

1. Is this for my child? Sport, age range, level, area of town.
2. When and where? Days, times, venue.
3. What does it cost? A real number, not "contact us".
4. Can we get in? Open, a few spots left, or waitlist.
5. Is it safe to try? Free first class, no payment details, who the coaches are.

**What they must do.** One thing: **request a free trial** with four fields (their name, email, optional phone, player's age) plus an optional class choice. Secondary: register directly, call or email, open the venue in maps. Existing families get one quiet "Parent login" link.

**Success.** A stranger on a phone can name a suitable class, its price and its times within 30 seconds, and submit a trial request within 60, without creating an account and without leaving the academy's own address.

**What is uniquely true here.** The listing is the live timetable the academy actually runs from (same sessions, coaches, capacity and prices the admin manages), so it cannot go stale the way a hand-edited Wix page does. That is the claim to the academy owner; the parent just sees a page that is obviously current.

## 2. Content

Sections, in page order. Everything is a single scrolling page in phase 1.

| # | Section | Content | Source |
|---|---|---|---|
| 1 | Night header (sticky) | Logo, academy name, "Parent login". From 800px: anchor nav and the trial button. | Academy profile |
| 2 | Hero | One sentence headline (sport + ages + place), one supporting sentence, primary "Book a free trial", secondary "See classes and prices", a line of 3 to 4 plain facts (age span, classes per week, first class free, venue). Hero photo if the tenant has one, otherwise a drawn court for their sport in their colour. | Academy profile + new public-page settings |
| 3 | Classes and prices | One question first: "How old is the player?" (All, 5 to 8, 9 to 12, 13 to 18, Adults). Classes grouped by **program** (name, level, age range). Each class row: days, time, coach (public display name), court/venue, price, availability ticket, "Try a class free" and "Register". | Sessions + new program fields |
| 4 | Free trial form | Inline section, not a modal. Reassurance ticks (no payment details, rackets provided, coach advice afterwards). Inline success state that says what happens next and when. | New public trial request |
| 5 | How joining works | Three steps: try, register, pay monthly. The sequence is real information, so numbering is earned. | Fixed copy, tenant can edit step 3 wording via billing period |
| 6 | Coaches | Public display name in full (as Pike13 and Mindbody staff listings do), one line of role or credential, optional photo from phase 3. Optional section; a coach can be excluded individually. | Coach display name + new optional public bio line and "show publicly" switch |
| 7 | Questions parents ask | 3 to 6 entries: what a trial is, what to bring, how payment works, missed classes, leaving. Seeded from the session "communication pack" fields where set. | New FAQ list + existing `what_to_bring`, `absence_policy` |
| 8 | Find us | Address with "Open in maps" link (no embedded map), coaching hours, phone, email, link for existing members. | Academy profile (`address`, `hours_text`, `contact_phone`, `contact_email`) |
| 9 | Footer | Parent login, Register, Privacy, Terms, "Bookings and payments by CourtMastr". | Fixed |
| - | Sticky bottom action (below 800px) | The primary action, always reachable by thumb. | Fixed |

**Deliberately left out**

- Testimonials, star ratings, student counts, "trusted by" rows. We have no real evidence and PRODUCT.md forbids inventing it. Add only when a tenant supplies real, consented quotes.
- Student names, photos of children, team rosters, results tables.
- A calendar grid. A week grid is unreadable at 400px and answers "what is on Tuesday?", which is not the stranger's question. Grouped rows answer "what fits my child?".
- Login or account creation before seeing price and availability (the main competitor weakness, see Sources).
- Embedded maps, chat widgets, cookie banners from third-party trackers, social feeds. They slow the page and add privacy surface. One maps link is enough.
- Blog, news, multi-page site building. This is a class page, not a website builder.
- Cross-academy anything (directory, "other academies near you"). Tenant isolation rule in PRODUCT.md.
- Coach phone numbers, coach emails, WhatsApp group links (those are for enrolled families only).

## 3. Theming: what a tenant can change and what stays fixed

**Principle: one colour in, a safe palette out.** The tenant supplies facts and one brand colour. They never pick text colours, backgrounds, fonts or spacing, so no combination of choices can produce an ugly or unreadable page.

### Tenant can set

| Setting | Notes | Exists today? |
|---|---|---|
| Academy name, address, hours, phone, email, timezone, currency | Already on the academy profile | Yes |
| Logo | Square, shown at 36px in the night header. If missing, a two-letter monogram on the brand colour. Logos that are not transparent sit on a white 8px plate. | `logo_url` yes (URL only, no upload) |
| Brand colour | One hex value. Drives buttons, links, the lane line under the hero, selected filter, step numerals, court drawing. | `brand_color` yes |
| Sport | Badminton or tennis. Picks the court drawing and default copy. | No |
| Hero headline and supporting sentence | 80 and 180 character caps. Sensible default generated from sport, age span and city. | No |
| Hero photo | Optional. Shown on the right at desktop, under the text on mobile, always with the night scrim so white text keeps contrast. No photo is a first-class state, not a fallback that looks broken. | No |
| Show price, show availability | Two switches, both default on. | No |
| What a price means | "Prices are per month / class / term", default month. Shown next to every price. | No |
| Show coaches | Academy-wide switch, plus a per-coach "show publicly" switch. | No |
| Program order, and which classes are listed | Drag order for programs; a per-class "Show on public page" switch. | No |
| Sections on/off | Coaches and FAQ can be hidden. Classes, trial and Find us cannot. | No |
| FAQ entries | Up to 8 question and answer pairs, plain text. | No |
| Free trials open or closed | One switch plus an optional "back on" date. | No |
| Page published | Master switch. Off means the public address shows the paused state. | No |

### Fixed for every tenant

- Typefaces (Outfit, Manrope, JetBrains Mono), type scale, spacing, corner radii, section order, and the flat, border-defined Rally surfaces.
- Night header and footer, paper and white content surfaces. The Floodlight Rule holds: the night areas are frame and billboard (header, hero, footer); everything the parent reads or fills in sits on paper or white.
- Status tickets use the frozen Rally status colours (green open, amber few left, yellow waitlist, slate by assessment), always a dot plus a word. **Tenant colour never touches status.**
- Focus ring is always Rally cobalt (#2563eb on light, #93c5fd on night and dark). **Tenant colour never touches focus.**
- Minimum 44px targets (48px for the main buttons), single column under 800px, safe-area padding on the sticky action bar.
- No custom CSS, no custom fonts, no free-form HTML.

**One deliberate change to a Rally rule.** In the app, cobalt is the only colour that means "do this". On this page the tenant's derived brand colour takes that job, and cobalt retreats to the focus ring. Volt appears once, in the CourtMastr shuttle mark in the footer. This should be recorded in DESIGN.md as a scoped exception for the public surface when it is built.

### Contrast guardrails (WCAG 2.1 AA)

The tenant's colour is never used raw. Five tokens are derived from it, server-side when the setting is saved and again in the admin preview:

| Token | Used for | Rule |
|---|---|---|
| `brand-fill` | Button and logo-tile background | The tenant colour as given, unless rule 3 below applies |
| `brand-on` | Text on `brand-fill` | 1. White if white is at least 4.5:1. 2. Otherwise Court Ink (#0f172a) if that is at least 4.5:1. 3. Otherwise (a narrow band of mid-tones where neither passes) darken the fill toward ink in small steps until white reaches 4.5:1. |
| `brand-text` (light) | Links, selected filter, step numerals on paper/white | Tenant colour darkened toward ink until at least 4.5:1 on #f8fafc |
| `brand-text` (night/dark) | Headline accent word, court lines, icons on night | Tenant colour lightened toward white until at least 4.5:1 on #101a2e |
| `brand-wash` | Trial section background, selected filter fill | 9% tenant colour mixed into the surface (16% in dark). Body text on it stays ink, which keeps well above 7:1. |

Proof in the prototype: Riverside's teal (#0f766e) needs no adjustment (white text, 5.5:1). Baseline's optic yellow-green (#bfd730) would be unreadable with white text; the rules switch button text to ink (11:1) and darken links on white to #63732d. The colour picker in the prototype control strip runs the same rules on any colour live.

Admin settings must show the result, not just accept the input: "Your colour is light, so button text will be dark", with a live preview. Never reject a colour; always make it work.

**Existing gap found while checking:** `backend/v2/shared/comms/email_theme.py:116` renders email buttons as white text on the tenant's `brand_color` with no contrast check. A light brand colour already produces failing emails today. The same derivation function should fix both surfaces.

## 4. URL model, SEO and sharing

**Addresses**

- Platform address (decided): `https://<slug>-academy.courtmastr.com/`, for example `riverside-academy.courtmastr.com`. This matches the host the production-ready tenant already uses (it appears in `DEPLOYMENT.md`, `backend/fly.toml` CORS origins and the auth-domain tests). It is a single label under `courtmastr.com`, so one wildcard certificate and one wildcard DNS record cover every academy.
- How that maps to the resolver: it matches `<label>.<platform_base_domain>`, so set `V2_PLATFORM_BASE_DOMAIN=courtmastr.com` and store the **whole label** (`riverside-academy`) as the tenant slug, or teach the resolver to strip a fixed `-academy` suffix. Storing the whole label needs no code change and is the recommendation. Reserve the labels the platform itself uses (`academy`, `api`, `www`, `status`, `app`) so no tenant can claim them.
- **Found while checking:** `backend/fly.toml` sets `APP_TENANCY_MODE=single_academy` and does not set `V2_PLATFORM_BASE_DOMAIN`. Single-academy mode makes this safe today, but the base domain must be set before multi-academy mode is switched on, because without it the resolver matches on the first label of any host.
- Custom domain: `https://classes.riversidebadminton.example/` or the apex. The resolver already maps custom domains to a tenant (ADR-0007 order: subdomain, then custom domain, then approved internal header).
- The public page is the **root path `/` on a tenant host**. On the platform's own host (`academy.courtmastr.com`, a reserved label) `/` stays the current product landing page (`frontend/app/page.tsx`). The frontend decides by asking the public API who the host belongs to; "no tenant for this host" renders the product landing page.
- Optional deep links in phase 2: `/#classes`, `/classes/<class-slug>` for a single shareable class. Phase 1 uses anchors only.

**Relation to existing pages**

- `/login` and `/register` stay where they are under `(marketing)` and already resolve the tenant from the host. The public page links to them on the **same host**, so the parent never sees a change of address or brand mid-journey (the most cited weakness of Jackrabbit and iClassPro portals).
- Phase 1 "Register" links to `/register` as is. Phase 2 adds `?class=<id>` so the chosen class is carried into onboarding after account creation. Today `/register` reads no such parameter (checked: no `searchParams` handling in `frontend/app/(marketing)/register/page.tsx`).
- `/login` and `/register` should pick up the tenant logo and `brand-fill` for their primary button in phase 2 so the three pages feel like one place.
- Single-academy mode (production today): the middleware rejects any host whose tenant is not `primary_academy_id`. The public page therefore works for the one tenant on its own host with no tenancy change. Multi-academy mode is what a second academy needs, and is a platform rollout step outside this brief.

**SEO basics** (server-rendered in Next.js with `generateMetadata`; none exists for a tenant today, and there is no `robots.ts` or `sitemap.ts`)

- `<title>`: `Badminton classes in Riverside for ages 6 to 18 | Riverside Badminton` (pattern: `{sport} classes in {city} for {age span} | {academy}`, 60 character target).
- Meta description: the hero supporting sentence plus "First class free.", 155 character cap.
- Canonical: the custom domain if one is verified, otherwise the `<slug>-academy.courtmastr.com` host. The other host 301s or sets canonical to it, so the page is never indexed twice.
- Open Graph and Twitter card: title, description, `og:image`. Phase 1 uses a generated card (academy name, sport, city on night with the brand lane line, 1200x630) so WhatsApp and Instagram previews look intentional even with no photo. Phase 3 uses the hero photo.
- Structured data (JSON-LD): one `SportsActivityLocation` (name, address, telephone, url, openingHours, logo) and, per listed class, a `Course` with `hasCourseInstance` (`courseSchedule` with `byDay`, `startTime`, `endTime`, `scheduleTimezone`) and an `Offer` (price, currency) when price is public. `FAQPage` for the FAQ section. Availability is left out of structured data because it changes hourly.
- `robots`: index when published; `noindex` for paused, unpublished and empty states. Per-host `sitemap.xml` with the root (and class pages in phase 2).
- Performance is part of SEO here: no client data fetch for first paint, fonts `display=swap`, no third-party scripts, hero image sized and lazy below the fold. Target LCP under 2s on 4G.

**Sharing**

- A "Share" action in phase 2 using the Web Share API with a copy-link fallback; links carry no personal data and no tracking parameters.
- Admin settings shows the public address with a copy button and a downloadable QR code for posters (phase 2).

## 5. Data and privacy

**Public allow-list.** The public endpoint returns a purpose-built view model and nothing else. It must be built from an explicit allow-list, never by serialising the `Session` or academy documents and removing fields.

| Public | Field | Notes |
|---|---|---|
| Academy | display name, sport, city, address, hours text, contact phone, contact email, logo URL, derived colour tokens, timezone, currency, hero text, hero image URL, FAQ, section switches | Contact email and phone are already meant for parents; tenant can blank either |
| Program | name, level label, min age, max age, short description, order | New fields |
| Class | public id (opaque, not the Mongo `session_id`), title, days of week, start and end time, timezone, venue name and address, coach public display name (omitted when the academy hides coaches or the coach is excluded), price and billing period (if price is public), availability **band** (if availability is public) | |
| Availability band | `open`, `few` with a number only when 3 or fewer remain, `waitlist`, `assessment` | Never capacity, never enrolled count |

**Never public, under any setting**

- Student names, ages, photos, skill levels, attendance, notes. Rosters and enrolled counts. Waitlist names or positions.
- Parent names, emails, phones, addresses, payment status, invoices, credits.
- Revenue, payouts, coach pay rates, `amount_cents` for classes the tenant has hidden prices on, Stripe account ids.
- Coach emails, phone numbers, user ids; assistant coach ids; any coach who is switched off for the public page.
- Internal ids (`academy_id`, `session_id`, `coach_id`), status reasons, plan codes, tenant limits, internal notes, `whatsapp_group_link`, `parking_notes` and `coach_contact_policy` (enrolled families only).
- Exact capacity and exact seats left above the "few" threshold. Exact numbers let a competitor or a curious parent reconstruct enrolment and revenue.

**Trial request (the only public write)**

- Collects: requester name, email, optional phone, player's age, optional class id. It deliberately does **not** ask for the child's name. The form says what the data is for and links to the privacy page.
- Stored tenant-scoped as a People CRM lead (decided). The CRM engineering spec (`docs/design/people-crm/engineering-spec.md`, main checkout) already defines the record for a lead with no parent account: `crm_contacts` (name, phone, optional email, source), with per-child pipeline status `lead` or `trial`. The public form creates exactly that record with a new source value `website`, the player's age, the requested class and the pipeline status `trial` (or `lead` for the "tell me when classes open" and waitlist variants). No account is created and the signed-in parent trial-requests queue is not used.
- Until the CRM screens ship, a lead must still reach a human: every submission also emails the academy's contact address through the existing Resend path, with the details and a reply-to of the parent.
- Abuse controls: reuse the rate limiter (`backend/v2/shared/http/rate_limit.py`, add the path to `_PUBLIC_WRITE_PATHS`), a honeypot field, server-side validation, size caps, and an emailed acknowledgement only through the existing Resend path (hard-blocked outside production). Note the limiter is in-memory per process, which is acceptable for phase 1 and listed as a known gap.
- Response is identical whether or not the email is already known, so the form cannot be used to discover who is a customer.

**Tenant isolation**

- Tenant comes only from the request host via the existing resolver. The endpoint takes **no** tenant, academy or slug parameter. `default_academy_id` is never consulted (the middleware already guarantees this).
- Set `platform_base_domain` in every environment that serves public pages. With it unset the resolver falls back to first-label matching, which `origins.py` itself flags as spoofable.
- Unknown host, suspended or cancelled tenant, and unpublished page all return the same 404 body, so the endpoint cannot be used to enumerate which academies exist (consistent with the "404 not 403" rule in PRODUCT.md).
- Cache keys include the resolved `academy_id`. Responses carry `Cache-Control: public, max-age=60` and `Vary: Host`; any CDN in front must key on host.
- All reads go through tenant-scoped repositories; add an import-linter-visible `public` interface package so the boundary is checked like the other personas.
- CORS: the public endpoints are same-site reads from the Next server, so no new browser origins are needed in phase 1.

## 6. What exists, what is missing, and delivery order

### Already in the code (verified 2026-09-20)

| Capability | Where |
|---|---|
| Tenant resolution by subdomain, then custom domain, then internal header, **before auth**, result on `request.state.resolved_academy_id` for public routes | `backend/v2/shared/tenancy/resolver.py`, `backend/v2/shared/auth/middleware.py` (lines 142 to 224), `backend/v2/shared/tenancy/origins.py`, `docs/adr/0007-saas-tenant-model-and-membership-auth.md` |
| Settings: `tenancy_mode`, `primary_academy_id`, `platform_base_domain` | `backend/v2/shared/config/settings.py` |
| Tenant slug, primary domain, status (`provisioning`, `active`, `suspended`, `cancelled`) | `backend/v2/contexts/platform/domain/models.py:32` |
| **Academy profile with branding already stored**: `display_name`, `timezone`, `contact_email`, `contact_phone`, `hours_text`, `address`, `logo_url`, `brand_color`, `currency` | `backend/v2/contexts/identity/application/get_academy_use_case.py`, `update_academy_use_case.py` |
| **Admin branding panel already exists** (logo URL field + colour field; its own note says logo upload is deferred until object storage exists) | `frontend/components/admin/settings/branding-panel.tsx`, `frontend/app/(admin)/admin/settings/page.tsx` |
| Same logo and colour already theme outbound email | `backend/v2/shared/comms/email_theme.py`, `backend/v2/composition/digests.py` |
| Session model: title, location, days of week, start and end time, timezone, capacity, `amount_cents`, coach, status, plus `venue_address`, `what_to_bring`, `absence_policy` | `backend/v2/contexts/enrollment/domain/models.py:204` |
| Catalog query that expands recurring sessions and computes seats | `available_for_parent_catalog` in `backend/v2/contexts/enrollment/infrastructure/mongo_session_repo.py:347`; route `GET /parent/sessions/available` requires the parent persona (`backend/v2/interfaces/parent/session_routes.py:23`) |
| Trial requests (no-charge, staff approval, conversion tracking), but only for a **signed-in parent** | `backend/v2/contexts/enrollment/application/use_cases/trial_requests.py`, migration `0145_parent_self_service.py` |
| Waitlist concept in the enrollment domain | `backend/v2/contexts/enrollment/domain/models_extra.py`, `events.py` |
| Rate limiting for public writes; TTL cache helper | `backend/v2/shared/http/rate_limit.py`, `backend/v2/shared/caching.py` |
| Unauthenticated pages and Rally tokens | `frontend/app/(marketing)/*` (login, register, privacy, terms, security, unsubscribe, auth), `frontend/app/page.tsx`, `frontend/tailwind.config.ts` |

**Corrections to the earlier session's findings.** Per-tenant branding storage **does** exist (`logo_url`, `brand_color`, with an admin panel). A trial-request concept **does** exist, but only behind parent login. Confirmed still true: there is no public catalog endpoint, no public (anonymous) trial or lead write, no image hosting, no tenant-aware metadata, `robots.ts` or `sitemap.ts`, and no frontend `middleware.ts`.

**Two things the parent catalog cannot be reused for as is:** it drops full classes entirely (the public page must show them as "Waitlist"), and it looks only 30 days ahead at occurrences, whereas the public page lists the recurring **class**, not dated occurrences. A sibling read method is needed, not a flag on the existing one.

### Missing pieces

| # | Piece | Size | Notes |
|---|---|---|---|
| A | Public read endpoint `GET /api/v2/public/academy` (profile + derived colour tokens + classes), new `backend/v2/interfaces/public/` package, use case, allow-list view model, tenant-scoped repo read, 60s cache, identical-404 behaviour, tests including a "no private field leaks" structural test | **M** | Needs a new persona-style prefix per `docs/agent/backend-api-rules.md` |
| B | Colour derivation function (the five tokens) shared by public page and email theme, with unit tests across the hue range | **S** | Also fixes the email contrast gap |
| C | Public page in Next.js: server-rendered route on tenant hosts, host-aware root, metadata, JSON-LD, generated OG card, all states | **M** | New route checklist applies: update the route audit manifest and the two route counts |
| D | **Program entity** (decided): name, level label, min and max age, short description, display order; each session belongs to one program. Per-class "show on public page" switch, **default off for every existing class** (decided). Tenant-level "prices are per month / class / term" setting, default month (decided). Per-coach "show publicly" switch and academy-level "hide coaches". | **M to L** | Session has no level, age, description or program today. Migration, admin program list, session form changes. Migrations are applied by hand in production. |
| E | Public-page settings in admin: publish switch, show price, show availability, trials open, sport, hero text, FAQ, live preview, public address with copy | **M** | Extends the existing branding panel |
| F | Anonymous trial request `POST /api/v2/public/trial-requests`: creates a `crm_contacts` lead (source `website`), rate limit, honeypot, acknowledgement email to the parent, notification email to the academy | **M** | This is the **first writer of `crm_contacts`**, so the collection, its migration and the create-contact use case are built here in the shape the People CRM spec defines, and the CRM adopts them rather than migrating later |
| G | Image hosting for logo, hero photo and coach photos (decided: build it). **Recommendation: the Firebase project's own Cloud Storage bucket.** `NEXT_PUBLIC_FIREBASE_STORAGE_BUCKET=academy-courtmastr.firebasestorage.app` is already in `frontend/.env.example`, the frontend Dockerfile and `DEPLOYMENT.md`, and `firebase-admin` is already a backend dependency, so there is no new vendor, account or secret. Shape: admin-only upload endpoint, server-side upload through the Admin SDK (the browser never writes to the bucket), type and size checks, re-encode and resize with Pillow (strips metadata, defeats disguised files), objects under `academies/<academy_id>/public/<kind>-<hash>.webp`, public read with a long cache lifetime, the returned URL saved into the existing `logo_url` field. Storage rules deny all client access. | **L** | Checked from repo config only. I could not see the live staging project, so before building confirm in the Firebase console that Storage is enabled on the staging project and whether staging has its own bucket. Nothing in the code uses the bucket today. Also unblocks the deferred logo upload in `branding-panel.tsx` and email signatures. |
| H | `/register?class=` preselect carried into onboarding; tenant logo and colour on `/login` and `/register` | **S to M** | |
| I | Public waitlist join, single-class share pages, QR code, Web Share | **M** | |
| J | Custom-domain self-service for tenants (DNS instructions, verification, certificates) | **L** | The resolver supports custom domains; onboarding them is manual today |
| K | Embeddable widget for academies that already have a website | **M** | Every competitor leads with this; we lead with the hosted page and add the embed later |

### Phased delivery

**Phase 1: smallest shippable page (A, B, C, D, F, minimal E).** Hosted page on the tenant host with identity, classes grouped by program, price, availability bands, FAQ from existing session fields, Find us, SEO metadata, and the **real trial form** writing People CRM leads and emailing the academy. Logo by URL, drawn-court hero, no photo. "Register" goes to `/register`. Minimal E is publish, show price, show availability, price period, trials open.

Why the real form and not a pre-filled email (the owner asked for the better option): the audience arrives inside WhatsApp and Instagram in-app browsers, where `mailto:` links often do nothing or open an unconfigured mail app; an email link records nothing, so the academy cannot count or follow up leads and the CRM pipeline starts empty; and the form is the whole point of the page. The cost is one M piece, and because it writes the CRM's own `crm_contacts` record it is work the People CRM needs anyway, not a throwaway. Tap-to-call and tap-to-email stay on the page as the fallback.

Suggested build order inside phase 1, each a separate PR: B (colour derivation, also fixes the email contrast defect), D (programs, publish switch, price period), A (public read), C (page), F (trial form), E (settings).

**Phase 2: polish the journey (H, rest of E).** Class preselect into registration, branded login and register, hero text and FAQ editing, live preview, leads visible in the People CRM pipeline as that ships.

**Phase 3: make it theirs (G, I).** Logo and hero photo upload, OG image from the photo, waitlist join, per-class share pages, QR code.

**Phase 4: reach (J, K).** Self-service custom domains and the embeddable widget.

## 7. States

| State | Trigger | What the parent sees | Primary action | Indexing |
|---|---|---|---|---|
| Classes open | Default | Full page | Book a free trial | index |
| Some classes full | Seats at zero on a class | That row shows a yellow "Waitlist" ticket; its button becomes "Join waitlist"; Register is removed from that row only | Book a free trial | index |
| **No classes published** | Published page, zero public classes | Identity and hero stay. Classes section becomes one calm notice: "The new timetable is on its way." The form becomes "Hear first when classes open" (name, email, age). Coaches, FAQ, Find us stay. | Tell me when classes open | noindex |
| **All classes full** | Every listed class at zero seats | A notice above the list explains that places open most months and waiting is free. Every row offers "Join waitlist". The form heading becomes "Join the waitlist". | Join the waitlist | index |
| **Trial requests closed** | Tenant switch, optional return date | Header and hero buttons become "See open classes". The "First class free" fact disappears. Rows keep "Register" only. The trial section becomes a notice with the return date, "See open classes" and "Contact us". | See open classes | index |
| **Academy paused** | Tenant `suspended` or `cancelled`, or page unpublished by the owner while the tenant is active | Header with logo and "Parent login" only. Headline: "{Academy} is not taking new players right now." Two actions: Parent login, Email the academy. Find us remains. No classes, no form, no sticky bar. For suspended or cancelled tenants the contact block is also removed and the API returns the identical 404 used for unknown hosts. | Parent login | noindex |
| Age filter has no match | Filter choice | One line: "No classes for this age group at the moment. Pick another age or ask us." | - | - |
| Form error | Missing or invalid field | One message under the fields naming the problem and the fix, focus moved to the first bad field, `role="alert"` | - | - |
| Form success | Valid submit | Form replaced in place by a confirmation that names the academy, says "within one working day", and states nothing is booked or charged yet. Focus moves to it. | Back to classes | - |
| Loading and failure | Server render fails or API is down | Server-rendered page has no loading state. On API failure show identity from cache if available, otherwise a plain "This page is having trouble. Try again in a minute." with the platform status untouched. Never a blank page. | Retry | - |

Realistic ranges the layout must hold: 1 to 40 classes, 1 to 8 programs, academy names up to 40 characters (header truncates with an ellipsis), class titles up to 60, 0 to 12 coaches, 0 to 8 FAQ entries, prices from free to four digits, currencies with symbols before or after the number.

## 8. Interaction and layout intent

- **Shape of the page.** A night billboard (header + hero) closed by a brand-coloured lane line, then a bright court of content. One tinted band (the trial section) interrupts the paper so the primary action has a place of its own. Night footer closes the frame.
- **The focal moment** is the hero: the headline in Outfit at up to 60px with one word in the tenant's colour, and the sport's court drawn in perspective in that colour, its lines drawing in once on load (off under reduced motion, and visible by default if the animation never runs). It is the one authored motion on the page. The court is the no-photo state, so every academy looks designed on day one.
- **Classes are rows, not cards.** Program heading with a heavy ink rule, then rows separated by hairlines. On a phone each row stacks: when, who and where, price and ticket, two full-width buttons. From 800px it becomes a four-column row. Times and prices use Outfit with tabular figures (the Scoreboard Rule).
- **One filter, phrased as the parent's question.** Toggle buttons with `aria-pressed`; the list region is `aria-live="polite"`.
- **"Try a class free" on a row** preselects that class in the form, scrolls to it and focuses the first field, so the parent never re-finds their choice.
- **No modals.** Nothing on this page needs protected focus.
- **Keyboard and screen reader.** Real buttons, links, labels, `details/summary` for FAQ; row buttons carry an `aria-label` naming the class and time; status is a word plus a dot; focus ring is never themed.
- **Dark appearance** follows the device. It is included because shared links open in whatever mode the phone is in. (The app itself has no dark theme; this does not change that.)

## 9. Owner decisions

All nine questions from the first draft were answered on 2026-09-20 and are recorded in the table at the top. Two notes:

**Why the footer credit was asked about.** "Bookings and payments by CourtMastr" does two jobs. It tells a parent who is handling their card details, which helps trust on a page they have never seen. And it is the product's only free advertising: every academy page is seen by other coaches and academy owners. Competitors sell its removal ("white label") as a paid upgrade, and an academy on its own custom domain may one day ask for that. Nobody has asked, so the decision is: **always on, nothing to build**, and revisit only as a paid option if a tenant requests it.

**Coach names, "industry standard".** Pike13 and Mindbody publish staff by full name with an optional photo and bio, and Jackrabbit lets the business show or hide an instructor column. So: full public display name by default, optional photo and one-line bio, the academy can hide coaches entirely, and any one coach can be left off. The display name is a field the coach or admin controls, so a coach who prefers "Coach Priya" can have that.

**Still open (small, can be settled during build):**

1. Tenant slug convention: store the whole host label (`riverside-academy`) as the slug (recommended, no resolver change) or store `riverside` and strip the `-academy` suffix in the resolver.
2. Whether staging has its own Firebase Storage bucket or shares the production project's. Needs a look in the Firebase console; it could not be checked from the repository.

## 10. Sources (competitor grounding)

How others expose a public listing, and what we take from it:

- **Jackrabbit Class**: an embeddable class listing table pasted into the customer's site; the business can hide any column except Register (including Openings and Tuition) with a `hidecols` parameter, and can enable trial enrolment per class in public registration. We copy the show/hide price and openings model and first-class trials; we avoid the dense table on phones. [Class listing tables](https://help.jackrabbitclass.com/help/online-class-listings), [Hide columns](https://help.jackrabbitclass.com/help/hide-columns-class-listings), [Trial enrolment](https://help.jackrabbitclass.com/help/trial-enroll-web-reg), [Client website examples](https://help.jackrabbitclass.com/help/client-website-examples)
- **iClassPro**: hosted customer portal with logo and primary and secondary colour, public filters by age, program, level and schedule, plus website integration buttons. We copy public filters without login. [Customer portal](https://www.iclasspro.com/customer-portal), [Website integration](https://support.iclasspro.com/hc/en-us/articles/360052567374), [Websites](https://www.iclasspro.com/websites)
- **Pike13**: embeddable schedule widget that hands off into Pike13's own enrolment flow, plus a branded app. [Schedule widget](https://help.pike13.com/hc/en-us/articles/360029876371-Schedule-Widget), [Branded app](https://www.pike13.com/product/features/branded-app)
- **Mindbody**: "branded web tools" widgets embedded by snippet, colours adjustable to match the site. No custom-domain support for the widget was found. [Branded web tools](https://www.mindbodyonline.com/business/branded-web-tools), [Intro](https://support.mindbodyonline.com/s/article/Intro-to-branded-web-tools)
- **CourtReserve**: a dedicated public booking link per club that needs no account, shareable by site, social and QR, plus an events calendar widget. Closest to our hosted-page model. [Public booking](https://help.courtreserve.com/en/articles/11787240-public-booking-setup-guide-and-overview), [Events calendar widget](http://help.courtreserve.com/en/articles/11558490-widgets-events-calendar), [Announcement](https://courtreserve.com/announcing-public-booking/)
- **Sawyer**: free embeddable list or calendar widget on the provider's site, and a marketplace that takes a discovery fee on marketplace bookings. We do not build a marketplace (tenant isolation, and no directory exists). [Widget guide](https://help.hisawyer.com/en/articles/11105559-widget-guide), [Widget embed](https://help.hisawyer.com/en/articles/11105551-what-is-a-widget-embed), [Third-party review](https://designtlc.com/archive/sawyer-class-management-review/)
- **Weakness to avoid**: parents being redirected mid-registration to a portal with a different brand and address. Source is a competitor's marketing blog, so treat as one data point: [Activity Messenger comparison](https://activitymessenger.com/blog/jackrabbit-vs-iclasspro-vs-activity-messenger/). That dated tables and iframes scroll badly on phones is our own impression, not sourced.

**Position we take.** Everyone else leads with an embed and treats the hosted page as secondary. Most small racquet academies have no real website, so we lead with a hosted page good enough to **be** their website, on their own address, with the embed as a later add-on.

## 11. Prototype notes

`docs/design/public-tenant-page/prototype.html` is one self-contained file for the artifact host (no doctype, html, head or body tags; Google Fonts is the only external resource). The dashed strip at the top is prototype tooling, not design: switch academy (Riverside Badminton / Baseline Tennis Club), switch page state (all five in section 7), force light or dark, and try any brand colour to watch the guardrails respond.

Smoke test, 2026-09-20, local static server with a wrapper supplying doctype and viewport meta: fonts loaded, no console errors, no horizontal overflow at 400px or 1200px in any of the five states for either tenant; class pick preselects and focuses the form; empty submit shows a named error and focuses the field; valid submit shows the confirmation and moves focus to it. The Impeccable detector's only two findings were on the prototype control strip and were addressed. Not published as an artifact.
