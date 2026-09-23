# Public tenant page B2: anonymous public academy read API (GET /api/v2/public/academy)

PR: #TBD

## What changed

- New unauthenticated persona package `backend/v2/interfaces/public/` with one route, `GET /api/v2/public/academy`. It takes no tenant, academy or slug input. The tenant comes from the request host through the existing `TenancyMiddleware` resolver. In production `single_academy` mode every host resolves to `PRIMARY_ACADEMY_ID`, so the live academy's page works on its own host and `APP_TENANCY_MODE` stays as it is.
- Responses:
  - No academy for the host, or no academy record: `404 {"detail": "Not found"}`.
  - Page not published: `state: "not_published"`, with the academy name, logo, `brand_color`, `brand_fill` and `brand_on_color` only.
  - Page published: `state: "published"`, with the academy profile (name, logo, colour tokens, venue `{address, hours_text}`, timezone, currency), the page switches (`trials_open`, `show_price`, `show_availability`, `price_period_default`, `privacy_notice_url`), published programs with their published classes, and `ungrouped_classes` for published classes with no active program.
  - Every response is sent with `Cache-Control: public, max-age=60` and `Vary: Host`.
- Colour tokens come from `shared/comms/colour.readable_button_colors`, the same function the email theme uses. An invalid or missing colour falls back to the product cobalt. The logo URL is checked again on read and only http(s) is accepted.
- Classes use opaque public ids (`c_…`, a one-way SHA-256 digest of academy + class id). The internal `session_id`, `program_id` and `coach_id` are never sent. The price is sent only when the academy shows prices, with the class's effective period (per month by default). Availability is sent only as a band: `open`, `few` with a number only when 3 or fewer seats remain, or `waitlist` for a full class. Exact capacity and enrolled counts are never sent. The coach name follows each class's `coach_display` (full name, first name or hidden), and a name that looks like an email is never shown.
- New `MongoSessionRepository.available_for_public_catalog()`. It sits alongside `available_for_parent_catalog`, which is unchanged. It lists published classes that are not cancelled or completed, including full ones. A weekly class is listed until its `end_date`, and a one-off class until it starts. Seats are counted from seat-holding enrollments (active and held), with `reserved_seats` as a floor.
- New use cases `ListPublicCatalog` (Enrollment) and `GetPublicAcademyProfile` (Identity, read-only, never upserts an academy). They are wired in the new `composition/public_page_read.py` at `app.state.public_page`. Nothing was added to `composition/admin.py`.
- Rate limit: `GET /api/v2/public/academy` allows 120 requests per client IP per 60 s in `InMemoryRateLimitMiddleware`.
- `TenancyMiddleware`: on `/api/v2/public/*` only, a tenant that cannot be served (suspended or cancelled) or a foreign tenant in single-academy mode now gets the same bare 404 as an unknown host. Before, it got a 423 or 403 whose body named the `academy_id`. Other paths are unchanged.
- Tests:
  - Structural no-leak test `tests/structural/test_public_page_dto_no_leak.py`. It walks the DTO field names recursively and checks every public route's response model. A behavioural pass seeds private data and checks that none of it appears in the response.
  - Unit and interface tests, including single-academy mode, 404s and rate limiting.
  - Real-mongod contract tests for tenant isolation, full classes and the 0194 index.

## Deploy notes

- No migration: B2 reads through the `sessions_academy_published` and `programs_*` indexes that migration 0194 (B1) creates. 0194 must be applied before this ships.
- No feature flag, no environment variable, no backfill. The page shows nothing until an admin publishes both the page (`public_page.published`) and at least one class.
- The rate limiter runs in memory in each process, so each Fly machine counts on its own. If the frontend server calls this route server-side, it must forward the visitor IP (`CF-Connecting-IP` with the proxy secret). Otherwise every visitor shares the server's bucket.

## Risk / rollback

- Low. This adds a read-only anonymous route. The tenant comes only from the host. The DTOs are allow-listed and a structural test guards them. The only change to existing behaviour is the 404-instead-of-423/403 answer on the new `/api/v2/public/*` prefix.
- Rollback: revert the PR. No data is written and there is nothing to undo in Mongo.
