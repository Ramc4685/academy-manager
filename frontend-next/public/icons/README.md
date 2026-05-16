# PWA Icons

Phase 0 ships placeholder icons (filenames listed in `manifest.webmanifest`).
Wave 1A replaces these with real artwork before the install prompts ship.

Required:

- `icon-180.png` — iOS apple-touch-icon
- `icon-192.png` — Android home screen
- `icon-256.png` — Android (Chrome menu)
- `icon-512.png` — Android (splash, app drawer)
- `icon-maskable.png` — 512×512, designed with 20% safe-zone padding

Generate from a single 1024×1024 source via `pwa-asset-generator` or any
equivalent tool. Commit the binaries to this folder.
