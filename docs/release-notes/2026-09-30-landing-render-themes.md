# Public landing page themes, content render and seats threshold (Settings Phase 6, PR 21-22)

PR: #TBD

## What changed

- **Two new page settings** (`academies.public_page`, saved by the existing `PATCH /admin/academy/public-page`, owner and admins): `theme` (`floodlit` | `daylight` | `showcase`, default `floodlit`) and `seats_left_threshold` (whole number 0 to 20, default 3, the value the seat chip has always used). Both are returned by the admin settings read and by the public read (`page.theme`, `page.seats_left_threshold`). Unset reads as today's values at read time, so no migration and nothing is backfilled.
- **Themes** (`frontend/lib/public-page/theme.ts`, pure and unit tested). Floodlit emits exactly the CSS it always did. Daylight is a light page (whatever the visitor's colour scheme) with the academy colour as accent. Showcase is Floodlit with a full-bleed hero photo under a dark scrim; with no photo it is Floodlit. Presets only, no colour picking. Every theme keeps text readable: text on a brand-coloured button clears WCAG AA 4.5:1 (pale brands get dark text, dark brands white, an in-between brand is darkened), brand-coloured text on Daylight is darkened until it clears 4.5:1, and Showcase text is checked against the worst-case photo pixel under the scrim.
- **Academy content is rendered when present** (optional fields on the public type, written by the content lane): hero photo, About us, highlights, a lazy-loaded gallery grid with fixed aspect ratio (caption is both the alt text and the visible caption), coach cards with photo and short bio (initials when no photo; a coach with no profile stays a name only), and the academy's own FAQs (built-in list when none). An academy that has written nothing renders exactly today's page.
- **Seats threshold is applied on the server**: the public catalog reports the "few" band (and the number) at or below the academy's threshold; 0 never shows "N spots left". A full class stays "Full, join waitlist" whatever the threshold. The chip wording is unchanged ("2 spots left").
- **Contact**: the page still shows the support email only. A structural test now also asserts no field in the public DTO mentions a phone.
- **Admin**: Settings > Public page has a Theme card (three swatches previewing the academy's own colour and logo) and a number field for the threshold next to "Show seat availability" (disabled while availability is off). Both save with the page's normal Save button.
- **Tests**: unit tests for contrast and themes (pale `#facc15`, dark `#0a0f1c`, a mid grey), seat threshold, render with and without content; backend tests for the fields, the threshold and rejection of bad values; e2e renders BLNO-style (Floodlit, no content) and a second academy host (Daylight, other colour, content, other support email) and asserts each shows only its own data.

## Deploy notes

No migration. BLNO renders exactly as before until an owner or admin changes the theme or threshold. Frontend and backend can deploy in either order: the new page fields are optional on the page and default to today's values on the server.

## Risk / rollback

Low. The only behaviour change for existing data is none: defaults equal today's look and the `FEW_SEATS_THRESHOLD` of 3 (pinned by a test). Roll back by reverting the PR; stored `theme` and `seats_left_threshold` keys are then ignored by the old code (`extra="ignore"`).
