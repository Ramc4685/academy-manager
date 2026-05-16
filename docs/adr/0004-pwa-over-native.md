# ADR-0004: PWA over native, Capacitor deferred

**Status:** Accepted
**Date:** 2026-05-16
**Deciders:** RamC (architect)
**Ticket:** P0-04

## Context

The product must be **installable on phones** and **fast on bad wifi** for the coach persona. The migration plan commits to a mobile-first redesign of the coach experience and an installable build. The question is *how* it gets onto phones: as a Progressive Web App, as a native iOS/Android app, or as a hybrid (Capacitor / React Native wrapping the web app).

Today there is no installable artifact. The CRA app loads in Safari/Chrome with no manifest, no service worker, and no install prompt. Phase 5 has not committed to a delivery channel.

## Decision

Ship a **Progressive Web App** as the installable artifact for all three personas. Use Serwist for service-worker tooling, a single `manifest.webmanifest` with maskable icons, and Safari/Chrome install prompts. **Defer native (iOS, Android, Capacitor-wrapped) until a concrete trigger fires.**

The PWA is the *only* delivery channel for the migration window. Frontend code is structured so a future Capacitor wrapper could ship without app-code rewrites if a trigger fires.

## Options Considered

### Option A: PWA only, native deferred (chosen)

**Pros:**
- One codebase, one deploy.
- No App Store / Play Store review cycles to block releases.
- No native SDK ramp-up.
- Install UX is real on Android Chrome (full A2HS) and serviceable on iOS Safari (with explicit instructions).
- Service workers + IndexedDB cover the offline-read requirement for Wave 1A.
- Lighthouse PWA score becomes a single, automatable quality bar.

**Cons:**
- iOS install flow is awkward — Safari does not surface a system install prompt automatically. We must show explicit "Add to Home Screen" instructions on first visit.
- No push notifications on iOS until iOS 16.4+ home-screen webapps, and even there with caveats. Push notifications are out of Wave 1A scope; if they become required, a Capacitor wrapper or a fresh native ADR is needed.
- No app store presence. Marketing surface narrower.

### Option B: React Native (Expo) from day one

**Pros:**
- Real native experience. Best perf ceiling. Full push notification support. App store presence.

**Cons:**
- Doubles the surface area: a React DOM app **and** a React Native app, with diverging component libraries (Tailwind doesn't work on RN; Radix is web-only).
- New deploy pipeline (EAS or Fastlane), code signing, store review.
- Three personas × two platforms = six surface areas to maintain. Far too much for one engineer.
- Rejected on cost.

### Option C: Capacitor (web app wrapped as native)

**Pros:**
- Web code runs unchanged inside a native shell.
- Push notifications, App Store presence available.
- Single codebase.

**Cons:**
- Adds a build artifact (`ios/`, `android/` folders) and a deploy lane.
- App Store review overhead per release.
- For the coach use case (phone install for field use), PWA is sufficient today.

**Not rejected, deferred.** This ADR specifies the triggers below.

### Option D: PWA + push via web push only

**Pros:** Stays inside the PWA model. iOS 16.4+ supports web push for installed PWAs.

**Cons:** iOS web push is patchy. Bypasses notification preferences on iOS in ways users find confusing. Defer until push is a real requirement.

## Capacitor Promotion Triggers

The PWA stays the delivery channel until **any** of the following becomes true. Each triggers a fresh ADR considering Capacitor or native:

1. **Push notifications become a product requirement** for any persona (e.g., coach session reminders, parent payment failure alerts).
2. **App store presence becomes a marketing or trust requirement** (e.g., academies expect "we have an app").
3. **A native platform integration is required** that the web cannot do (camera with specific format, contacts, deep file system access, in-app purchases).
4. **iOS install friction measurably hurts coach adoption** — measured by tracked install-prompt-shown vs install-completed metrics dropping below an agreed threshold (TBD when we have the baseline from W1A-19).

Until then, no native work, no Capacitor scaffold, no app store registrations.

## Frontend Structure for Future Capacitor

The frontend is built so a future Capacitor wrap is mechanical:

- All API calls go through `lib/api/client.ts`. Adding a base URL override (web vs. Capacitor) is one line.
- Auth uses Firebase Web SDK; Capacitor compatibility is maintained (Firebase JS SDK works in Capacitor WebViews).
- No browser-specific globals leak outside `lib/`.
- The service worker is registered conditionally; under Capacitor, the SW is skipped and Capacitor's own asset pipeline handles offline.

These are zero-cost choices at PWA-time and become valuable if a trigger fires.

## Consequences

**Becomes easier:**
- Single delivery channel; release process is `git push → deploy`.
- Install UX is verifiable via Lighthouse + manual real-device check.
- Offline reads via Serwist (Wave 1A scope) are the proven path.

**Becomes harder:**
- iOS users get an explicit "Add to Home Screen" card on first visit. Acceptable; small one-time UX cost.
- No push notifications. Communication relies on in-app messages (Wave 3) and email.

**To revisit:**
- Any Capacitor promotion trigger above. New ADR required.

## Action Items

1. [x] Reject native-from-day-one and same-day-Capacitor options.
2. [ ] Implement Serwist + manifest + install prompt scaffolding (P0-18).
3. [ ] Build coach install-prompt flow with iOS instructions (W1A-15).
4. [ ] Track install-prompt-shown vs install-completed in observability (W1A-19) to detect trigger #4.
