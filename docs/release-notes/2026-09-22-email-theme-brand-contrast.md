# email-theme-brand-contrast

PR: #909

## What changed

- New shared module `backend/v2/shared/comms/colour.py` with WCAG 2.x contrast math and `readable_button_colors(fill) -> (background, text)`: white text if it reaches 4.5:1 on the brand colour, otherwise Court Ink, otherwise (a narrow band of mid-greys where neither passes) the fill is nudged toward the nearer extreme until one does. Invalid hex raises; the fallback-to-cobalt decision stays with `EmailBrand.accent()`.
- The primary email button (`email_theme.button`) now paints its background, text and border from that derived pair instead of hardcoding white text on the accent. The secondary variant and the default cobalt button render byte-for-byte as before.
- Why: a light tenant `brand_color` (yellow, near-white) would have produced an unreadable call to action. The same rule is the `brand-fill` / `brand-on` derivation the public academy page brief asks for, so that page can reuse the function unchanged.
- `email_theme.button` normalises its `accent` itself: a non-hex value degrades to cobalt instead of raising at send time, so a caller that bypasses `EmailBrand.accent()` still renders a readable button.
- The public academy page brief words the mid-tone rule as "darken toward ink until white passes"; the shipped function nudges toward whichever text colour is nearer to passing (less fill movement, as the ticket specified). The module docstring names this function as the single `brand-fill` / `brand-on` rule so the page reuses it and the brief's wording is aligned when that page is built.
- Unit tests cover the light/dark/mid brand-colour matrix, the nudge branch and its direction, invalid input, and the rendered button HTML.

## Deploy notes

None. No migration, no settings, no route change. Today every production call site uses the default cobalt accent, so outbound mail does not change until a branded button is wired in.

## Risk / rollback

Low. Pure function plus one style string in the shared email theme; no data or auth path touched. The nudge blends in sRGB rather than a perceptual space, so a mid-grey brand colour can shift slightly in tone while gaining contrast. Rollback is a plain revert of the PR.
