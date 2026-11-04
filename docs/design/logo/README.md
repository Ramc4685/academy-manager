# CourtMastr Academy logo: Earned Stripes

Chosen by the owner on 2026-11-03, after three rounds (`../app-icon/`, `../logo-round2/`, `../logo-round3/`).
It replaces the CM monogram as the app icon and is the product's logo.

**Idea:** levels earned, stacked like stripes; the newest one is volt. It says academy (players
progress level by level, which is what the app tracks), and it fits any racket sport because no
racket or ball is drawn.

## Construction

Three chevrons on a 3:4 slope (60 across, 45 up), 50 units apart, 24 units thick, mitred apex,
square ends, on a 256 grid. The ink box is 135 x 170 and sits 3 units above centre (optical
centre). Everything is generated from `build_logo.py`; change the geometry there, then run
`python3 build_logo.py`.

The wordmark is Outfit (the app's display face, SIL Open Font License, so logo use is allowed),
outlined to paths: "CourtMastr" at weight 700 with -2% tracking, and "ACADEMY" at weight 600 with
24% tracking. The outlines are stored in `wordmark-paths.txt`, made with `outline_wordmark.py` from
`frontend/app/fonts/outfit-latin.woff2` (`uv run --with fonttools --with brotli python outline_wordmark.py <font> <text> <weight> <tracking>`).
The SVGs contain no live text.

## Colours (Rally palette, `DESIGN.md`)

| Use | Colour |
|---|---|
| Background, dark | Floodlit Night `#0a0f1c` |
| Stripes and wordmark on dark | Paper `#f8fafc` |
| Top stripe and ACADEMY on dark | Floodlight Volt `#facc15` |
| Stripes and wordmark on light | Court Ink `#0f172a` |
| Top stripe and ACADEMY on light | Line Gold `#a16207` (volt is too faint on white: 1.5:1) |

One-colour black and white versions are for print, embroidery and single-colour use.

## Files

| File | Use |
|---|---|
| `symbol-dark.svg` | Primary symbol on a rounded night tile (avatars, favicon) |
| `symbol-on-dark.svg` / `symbol-on-light.svg` | Symbol alone, transparent |
| `symbol-black.svg` / `symbol-white.svg` | One colour |
| `lockup-horizontal-light.svg` / `-dark.svg` | Main logo: symbol + CourtMastr / ACADEMY |
| `lockup-stacked-light.svg` / `-dark.svg` | Square spaces (posters, splash, merch) |
| `lockup-horizontal-black.svg` / `-white.svg` | One colour |
| `app-icon.svg` | Full-bleed square icon source |
| `board.html`, `board/` | Presentation slides with mockups |

## Store and app slots (`export/`)

| File | Goes to |
|---|---|
| `ios-app-store-1024.png` | App Store Connect icon. Opaque RGB, square corners (Apple applies the mask). Also `mobile/assets/icon-only.png`. |
| `android-adaptive-foreground-1024.png` | `mobile/assets/icon-foreground.png`. Full scale on purpose: `mobile/android/.../mipmap-anydpi-v26/ic_launcher.xml` insets the layer 16.7%, which keeps the stripes inside the 66dp safe circle. |
| `android-adaptive-background-1024.png` | `mobile/assets/icon-background.png` |
| `play-store-icon-512.png` | Play Console, App icon |
| `play-feature-graphic-1024x500.png` | Play Console, Feature graphic |
| `splash-2732.png` | `mobile/assets/splash.png` and `splash-dark.png` |
| `web/` | favicon.ico/svg, 16/32/48 PNGs, apple-touch-icon (180), icon-192/512, maskable-512 for the web app. Not yet wired into `frontend/public/`. |

After changing any `mobile/assets` file, run `pnpm assets` in `mobile/`, then restore
`android/app/src/main/AndroidManifest.xml`, which the generator reformats for no reason.

## Usage

- **Clear space:** keep a margin around the logo of at least one stripe gap (the distance between
  two chevrons, about 30% of the symbol's height).
- **Minimum size:** symbol 16px; horizontal lockup 120px wide; drop "ACADEMY" below 160px wide.
- **Backgrounds:** night or white/paper. On photos, put the logo on a night tile.
- **Don't:** rotate or flip the stripes (they point up because players move up), change the
  order of colours, make the volt stripe anything other than the top one, add outlines,
  shadows or gradients, or retype the wordmark in another font.

## Open items

- Trademark search for the name and mark has not been done.
- Web and PWA icons (`frontend/public/icons`, `favicon.ico`) still show the house academy "B".
  The set in `export/web/` is ready to swap in once the frontend is free to edit.
