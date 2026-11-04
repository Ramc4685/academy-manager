# CourtMastr Academy app icon (superseded)

> Superseded on 2026-11-03 by the Earned Stripes logo in `../logo/`. The CM monogram below was
> briefly wired into `mobile/`; the store files now come from `../logo/export/`.

Picked by the owner on 2026-11-03: **CM monogram**. A volt "C" drawn like court boundary paint
wraps a white "M", set on Floodlit Night. It replaces the house academy's yellow "B" (one tenant's
brand) with the product's own mark. Colours come from the Rally palette in `DESIGN.md` and
`frontend/tailwind.config.ts`: night `#0a0f1c`, volt `#facc15`, paper `#f8fafc`. It is
sport-neutral and has no text beyond the monogram.

## Sources (SVG)

| File | What |
|---|---|
| `courtmastr-icon.svg` | Full-bleed icon tile (mark on night) |
| `courtmastr-mark.svg` | Mark only, transparent |
| `courtmastr-icon-foreground.svg` | Android adaptive foreground (transparent) |
| `courtmastr-icon-background.svg` | Android adaptive background (solid night) |
| `splash.svg` | 2732 splash, mark centred on night |
| `play-feature-graphic.svg` | 1024x500 Play feature graphic (uses system fonts; check the PNG, not the SVG) |

## Store slots (`export/`)

| File | Goes to |
|---|---|
| `ios-app-store-1024.png` | App Store Connect app icon. 1024x1024, opaque RGB, square corners (Apple applies the mask). Also `mobile/assets/icon-only.png`. |
| `android-adaptive-foreground-1024.png` | `mobile/assets/icon-foreground.png`. The native template insets this layer 16.7%, so the PNG fills the central 72dp of the 108dp icon and the mark stays inside the 66dp safe circle. |
| `android-adaptive-background-1024.png` | `mobile/assets/icon-background.png` |
| `play-store-icon-512.png` | Play Console, Store listing, App icon (512x512) |
| `play-feature-graphic-1024x500.png` | Play Console, Store listing, Feature graphic |
| `splash-2732.png` | `mobile/assets/splash.png` and `splash-dark.png` |

Regenerate the native sizes from `mobile/` with `pnpm assets`. The script's background colours are
now `#0a0f1c`. `mobile/android/app/src/main/res/values/ic_launcher_background.xml` was changed by hand
to `#0A0F1C` because the generator does not write it. The generator also reformats
`AndroidManifest.xml`; restore that file afterwards, since the change does nothing.

## Explorations

`explorations/` holds the first round: A (shuttle, from the platform `ShuttleMark`), B (service box),
C (court C), the CMA variant, and `compare.html` / `compare.png`, which show each direction at real
sizes on light and dark home screens. Trademark clearance for the CM mark has not been checked.
