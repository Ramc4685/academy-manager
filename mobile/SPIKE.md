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

## Device run, 2026-11-03 (Android emulator, API 37, local stack)

`adb reverse tcp:3001 tcp:3001` and `adb reverse tcp:9099 tcp:9099` let the
emulator use `localhost` for the dev server and the Firebase Auth emulator, so
the Android build needs no `MOBILE_SERVER_URL` override. Gradle 8.14 needs
JDK 21 (`brew install openjdk@21`); Android Studio's bundled JDK 25 fails.

- Shell boots, opens `/login`, academy branding resolves after seeding. Pass.
- Email sign-in → admin dashboard, then Log out → back to `/login`. Pass, no crash.
- Google sign-in: without `google-services.json` the native auth plugin fails
  to load, so the button is now hidden in the app (the web fallback opened
  Chrome, which Google blocks in webviews anyway). Needs the Firebase file.
- Push: stays off on Android until `google-services.json` is bundled. No crash.
  (Run with the old push plugin and its PushReady guard; since replaced by
  `@capacitor-firebase/messaging`, which rejects `getToken()` instead. Not re-run.)
- Not covered: Stripe Checkout (no local Stripe keys), offline attendance
  (service worker is off in `next dev`), iOS (Xcode license needs `sudo`).

### Second pass, 2026-11-03 01:20–01:35 (production build via `pnpm build && pnpm start`)

- Start URL is now `/post-login`: a signed-in coach relaunching the app lands on
  Today instead of the sign-in form. Pass. On the emulator (software GPU) the
  cold start to Today takes ~30s; recheck on a real phone before worrying.
- Service worker runs inside the Android WebView (checked over DevTools:
  page controlled, `pages` and `coach-api-v1` caches filled). With the server
  cut (`adb reverse --remove`), a relaunch rendered the cached page. Pass, but
  only after a page has been visited once online; a first-ever offline launch
  shows Android's "Webpage not available".
- `@capacitor-firebase/messaging`: permission prompt shows once; with no
  `google-services.json`, `getToken` rejects and the app keeps running. Pass.

## Device run, 2026-11-03 (iOS simulator, iPhone 18 Pro, iOS 27.2, local stack)

Built with Xcode 27.2. The first build took ~58 min (Firebase SPM checkout);
incremental builds take ~1 min. `Package.resolved` is committed so the Firebase
pins stay put.

- Launch → branded sign-in → coach sign-in → Today. Pass.
- Push permission prompt → granted; with no `GoogleService-Info.plist` Firebase
  logs "not configured" and the app keeps running. Pass.
- "Continue with Google" without the plist shows an inline error, no crash.
  Needs the Firebase file to test for real.
- Sign-out originally opened Safari: iOS treats any top-level load whose URL does
  not start with `server.url` as external, and `server.url` held `/post-login`.
  Fixed: `server.url` is now the bare origin and the start route moved to
  `server.appStartPath`. iOS also requires `www/<appStartPath>` to exist locally
  before it will start, hence the `www/post-login/` placeholder. Pass after fix;
  Android re-checked with the same config (opens `/post-login` → home). Pass.
- Offline relaunch with the frontend stopped renders the cached sign-in page from
  the service worker. Pass.
- Open issue (also on the website in mobile Safari): inputs under 16px (`text-sm`)
  make iOS zoom in on focus, and the zoom persists after navigation, so the next
  page looks cut off on the left. Fix belongs in the web UI, not the shell.
- Not covered: Stripe Checkout, real push send, Sign in with Apple (needs a paid
  team), physical device.
