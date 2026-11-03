# Mobile shell spike (Capacitor)

Status: shell scaffolded and configured, not yet run on a device (2026-11-02).

## What exists

- `mobile/` is a standalone Capacitor 8.5 package (pnpm). `ios/` uses Swift Package
  Manager (no CocoaPods); `android/` is a plain Gradle project.
- The shell loads the deployed Next.js app via `server.url` instead of bundling it,
  because the frontend renders on the server (OpenNext on Cloudflare Workers).
  `MOBILE_SERVER_URL` picks the target at `pnpm sync`; the default is the local dev
  server on `http://localhost:3001`.
- `appId` is `com.courtmastr.academy`. It is permanent once an app is published, so
  confirm it before the first store upload.

## Running it

Needs full Xcode (App Store) and Android Studio, plus roughly 50 GB of free disk.

```bash
cd mobile && pnpm sync && pnpm ios
```

```bash
cd mobile && MOBILE_SERVER_URL=http://10.0.2.2:3001 pnpm sync && pnpm android
```

## The five risky flows

| Flow | What the code says | Expected in the shell | Verified on device |
|---|---|---|---|
| Google sign-in | `lib/auth/firebase.ts` uses `signInWithPopup` / `signInWithRedirect` | Google blocks OAuth in embedded webviews (`disallowed_useragent`); needs the native plugin `@capacitor-firebase/authentication` then `signInWithCredential` | No |
| Email sign-in | `signInWithEmailAndPassword` | Should work unchanged | No |
| Stripe Checkout | Parent checkout sends `success_url`/`cancel_url` from the frontend (`lib/api/parent.ts`) | Capacitor opens unlisted hosts in the system browser, stranding the return; `checkout.stripe.com` is in `allowNavigation` and `WKAppBoundDomains` to keep it in the webview | No |
| Coach offline attendance | Serwist service worker | iOS WKWebView only runs service workers for App-Bound Domains; `limitsNavigationsToAppBoundDomains` + `WKAppBoundDomains` are set. Side effect: every in-webview host must be listed (max 10) | No |
| Academy resolution | Only `/` is host-aware (`app/page.tsx`); persona routes resolve the academy from the signed-in user | Less risky than first thought: the shell should open the product host and send users to login, not `/` (which would show the marketing landing) | No |

## Open questions for the device run

- Does App-Bound Domains mode break Firebase auth helpers or any third-party script
  host the app loads (Sentry, fonts)? Each needed host goes in `WKAppBoundDomains`.
- Is there a staging deployment? None is referenced in the repo; until there is one,
  the spike targets local dev.
- Start URL: point `server.url` at `/login` (or a post-login route) rather than `/`.

## Icon and splash

Sources live in `mobile/assets/` (1024px icon, adaptive foreground/background,
2732px splash on `#0a0a0a`), drawn from the PWA mark in `frontend/public/icons`
(yellow `#ffd21f` tile, navy `#06121f` "B"). Regenerate every native size with
`pnpm assets`. The generator also reformats `android/app/src/main/AndroidManifest.xml`;
discard that diff, it changes nothing. The "B" is the house academy's mark; replace
the five source files if the store app gets its own brand, then rerun `pnpm assets`.
