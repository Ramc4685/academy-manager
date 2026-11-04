# Publishing the mobile app to the App Store and Google Play — ordered checklist

Status: checklist, 2026-11-03. Nothing here has been started in either store.
Builds on `docs/plans/2026-11-02-mobile-apps.md` (slices M0–M7),
`docs/plans/2026-11-03-store-listing.md` (M6 answers) and
`docs/plans/2026-11-03-account-deletion.md` (M5). Those docs hold the detail; this one
holds the order, the owner, the cost and the wait.

**Who:**
- **OWNER-ONLY** — payment, identity, legal agreements, passwords, signing keys and other
  secrets, final "Submit". Only RamC can do these.
- **ASSISTANT-OK** — an AI assistant with browser/computer control can do it once the
  owner is signed in (form filling, console clicks that create no secret).
- **CODE** — repo work for Claude Code in this worktree; ends in a PR the owner approves.

## Status at a glance (2026-11-03)

**Done**
- Marvy Labs LLC registered; `https://marvy-labs.com` live with contact + privacy links.
- Capacitor 8.5 shell (`mobile/`), start URL `/post-login`, release builds refuse non-https URLs.
- Android emulator pass: email sign-in, sign-out, post-login routing, offline attendance via
  the service worker, push permission prompt without crashing.
- Native Google / Apple sign-in code (M1), push device registration backend (M2) and app
  push (M4) built on local branches; nothing pushed, not run on a real device.
- Icon and splash generated from `mobile/assets/`.
- Xcode 27.2 installed (meets Apple's Xcode 26 minimum); Android targets API 36 (meets Play's rule).
- `/privacy` and `/terms` pages exist (privacy still a draft).
- Plans written: app slices, store-listing answers (privacy label, data safety, age
  rating), account-deletion design, this checklist.

**Owner only** (payment, identity, agreements, passwords, secret keys, final submit)
1. D-U-N-S for Marvy Labs LLC: the assistant can fill the lookup form; you confirm the details (1.3).
2. Apple Developer enrollment as an organization: pay $99, accept the agreement, take Apple's verification call (1.4–1.5).
3. Google Play organization account: pay $25, verify identity, phone and email (1.6).
4. Decisions: store name, bundle id, iPhone-only, US-only, icon (1.7, 1.8, 4.3).
5. The 11 account-deletion retention decisions, then counsel review of the privacy policy (1.9).
6. Apple key (.p8) for push + Sign in with Apple; upload it to Firebase (2.3, 2.4).
7. Sign in to Xcode; type the Android keystore passwords; store both in your password manager (2.6, 3.5).
8. Reviewer demo logins (set their passwords) (4.1).
9. Approve each PR/push; press the IARC submit, "Submit for Review" and "Send for review" (4.7, 6.2, 6.3).

**Your computer assistant** (once you are signed in): 2.1, 2.2, 2.5, 1.2's email
route, 4.2, 4.4–4.9 (fill, not final submit), 5.1, 5.3, 5.4, 6.1, using the prompt block below.

**Claude Code** (repo PRs): Phase 3 (3.1–3.8) and moving the support email to `@marvy-labs.com`.

## Bottom line

- **Cash: about $124 the first year** ($99/yr Apple + $25 once Google), plus whatever
  counsel charges to review the privacy policy. Publisher: Marvy Labs LLC (registered). D-U-N-S is free; do not pay Dun & Bradstreet to expedite.
- **Calendar: about 4–8 weeks**, set by the D-U-N-S number → Apple organization
  verification chain (1–5 weeks) running in parallel with the code still to build
  (account deletion, release signing, push sending; roughly 2–3 weeks of PRs). App Review
  itself is usually 1–3 days, plus one more round if Apple raises 4.2 (minimum
  functionality).
- **Website: OK.** The organization site is `https://marvy-labs.com` (live, real content,
  Contact and Privacy links, `hello@marvy-labs.com`, Cloudflare Email Routing). Use it
  for Apple and Google enrollment, and enroll with an `@marvy-labs.com` address.
  Domain mismatch to fix: the app's support address (`frontend/lib/brand.ts`,
  privacy page) is `support@marvylabs.com`, on the **unhyphenated** `marvylabs.com`,
  which has GoDaddy mail but no website. Move store and app contact addresses to
  `@marvy-labs.com` so the seller, website and support email all match.
- **Blocker found while writing this:** the live `https://academy.courtmastr.com/privacy` still shows "Draft privacy
     summary. Review with counsel before production…". Both stores check the policy
     against the privacy answers.

## Phase 1 — Accounts and legal (start today; this is the critical path)

| # | Step | Who | Cost | Lead time | URL |
|---|---|---|---|---|---|
| 1.1 | Publishing entity: **Marvy Labs LLC** (registered, owner confirmed 2026-11-03). Use the exact registered name and address everywhere: D-U-N-S, Apple enrollment, Google Payments profile. Apple shows it as the seller name. Keep the LLC's annual report current; a lapsed entity fails verification. | OWNER-ONLY | $0 | Done | — |
| 1.2 | Website: `https://marvy-labs.com` is live and qualifies. Optional: add a CourtMastr product page or link to the app's privacy and terms pages. Create a mailbox or route for the enrollment email (e.g. `ramc@marvy-labs.com`) and switch the app's `support@marvylabs.com` to `@marvy-labs.com` (CODE: `frontend/lib/brand.ts` + privacy page). | ASSISTANT-OK (Cloudflare Email Routing rule); CODE (address change) | $0 | 1 hour | https://dash.cloudflare.com (Email Routing for `marvy-labs.com`) |
| 1.3 | Look up or request the entity's D-U-N-S number. Use Apple's lookup tool first; it submits the request to D&B for free if none exists. The legal name and address must match the state registration exactly, and later the Google Payments profile. | OWNER-ONLY (identity data) | Free | Apple tool: often ~5 business days; D&B says up to 30 days | https://developer.apple.com/enroll/duns-lookup/ · https://www.dnb.com/duns/get-a-duns.html |
| 1.4 | Apple Account for enrollment: legal first/last name (no company name in those fields), two-factor on, email on the entity's domain. | OWNER-ONLY | $0 | Same day | https://account.apple.com |
| 1.5 | Enroll in the Apple Developer Program **as an organization** (after D-U-N-S arrives). Apple may phone to confirm authority to bind the company. Accept the Program License Agreement, pay. | OWNER-ONLY | **$99/year** | ~2 days to 2 weeks verification | https://developer.apple.com/programs/enroll/ |
| 1.6 | Google Play Console **organization** account (needs the same D-U-N-S). Set up the Google Payments profile with the exact D&B name/address; verify contact + developer email and phone by one-time code. Organization accounts skip the 14-day / 12-tester closed test that new personal accounts must run before production. | OWNER-ONLY | **$25 once** | Payment check up to 5 days; identity checks typically days | https://play.google.com/console/signup |
| 1.7 | Decide app name (30 chars both stores; "Academy" alone is too generic), confirm bundle id `com.courtmastr.academy` (permanent after first upload), category (Education primary, Sports secondary), iPhone-only vs iPad (iPad needs its own screenshots). Recommendation: iPhone-only for v1. | OWNER-ONLY (decision) | $0 | — | — |
| 1.8 | Decide distribution countries. Recommendation: **United States only** for v1, which avoids the EU Digital Services Act "trader status" declaration (public address/phone on the EU listing). | OWNER-ONLY | $0 | — | App Store Connect → Pricing and Availability |
| 1.9 | Privacy policy: answer the 11 account-deletion retention decisions (`2026-11-03-account-deletion.md`), get counsel review, then remove the draft banner. Claude drafts the rewrite (slice D5). | OWNER-ONLY (decisions, counsel); CODE (rewrite) | Counsel: varies, $0–$1,500 est. | 1–2 weeks | https://academy.courtmastr.com/privacy |

The app is free, so no Paid Apps agreement, tax forms or bank account are needed in App
Store Connect or Play. Classes are paid through Stripe as services consumed outside the
app, which both stores allow (Apple 3.1.3(e)); say so in the review notes.

## Phase 2 — Firebase and Apple capabilities (after 1.5; Firebase part can start now)

| # | Step | Who | Cost | Lead time | URL |
|---|---|---|---|---|---|
| 2.1 | Firebase console, existing project: add an **iOS app** and an **Android app** with the confirmed bundle id. Download `GoogleService-Info.plist` and `google-services.json` and hand them to Claude (they go in `mobile/ios/App/App/` and `mobile/android/app/`; neither is in the repo yet). | ASSISTANT-OK | $0 | 15 min | https://console.firebase.google.com |
| 2.2 | Apple Developer → Identifiers: register App ID `com.courtmastr.academy`; enable **Sign in with Apple** and **Push Notifications**. | ASSISTANT-OK | $0 | 10 min | https://developer.apple.com/account/resources/identifiers/list |
| 2.3 | Apple Developer → Keys: create one key with **APNs** and **Sign in with Apple** enabled; download the `.p8` (downloadable once). Upload it in Firebase → Project settings → Cloud Messaging (APNs auth key, with Key ID + Team ID). | OWNER-ONLY (secret key file) | $0 | 15 min | https://developer.apple.com/account/resources/authkeys/list |
| 2.4 | Firebase → Authentication → Sign-in method: enable **Apple**; fill Team ID, Key ID and private key in its OAuth section (needed for token revocation on account deletion). Google provider is already on. | OWNER-ONLY for pasting the key; rest ASSISTANT-OK | $0 | 10 min | https://firebase.google.com/docs/auth/ios/apple |
| 2.5 | Android Google sign-in: add the **debug**, **upload** and **Play App Signing** SHA-1/SHA-256 fingerprints to the Firebase Android app. The Play App Signing one only exists after the first upload (Play Console → Test and release → App integrity); without it Google sign-in fails in the store build but works in local builds. | ASSISTANT-OK (Claude prints debug/upload ones) | $0 | 10 min, twice | Firebase → Project settings → Android app |
| 2.6 | Xcode: sign in with the Apple ID (Settings → Accounts), select the team on the App target; confirm Push Notifications, Sign in with Apple and Background Modes → Remote notifications appear. | OWNER-ONLY (password) | $0 | 10 min | Xcode (27.2 installed; Apple requires Xcode 26+ / iOS 26 SDK since 2026-04-28) |

## Phase 3 — Code still to build (CODE; Claude Code in this worktree, one PR each)

Order matters: 3.1 and 3.2 gate the first submission; 3.3–3.6 gate the first signed build.

| # | Step | Who | Est. effort | Blocked on |
|---|---|---|---|---|
| 3.1 | **M5 account deletion**, slices D1 (backend request) → D2 (Delete account on parent + coach profile, re-auth, Apple revocation) → D3 (executor) → D4 (admin visibility + public `/account-deletion` page, 404 today) → D5 (privacy rewrite). Apple 5.1.1(v) needs it started in-app; Google needs the web URL in the Data safety form. Retained data (invoices, payments, 7 years) must be disclosed on the screen and in the policy, which both stores allow. | CODE | ~1–2 weeks | Owner retention decisions (1.9) |
| 3.2 | **Push sending (M3)** + land M2/M4 (built locally, unpushed). Apple 4.2 rejects thin web wrappers; push is the strongest native feature. Fix the M2 token-takeover risk first (plan doc, Risks). | CODE | ~3–5 days | 2.1, 2.3 |
| 3.3 | **Production server URL**: add a `pnpm sync:release` script that runs `MOBILE_RELEASE=1 MOBILE_SERVER_URL=https://academy.courtmastr.com cap sync` (the config already refuses a non-https URL when `MOBILE_RELEASE=1`, so `cleartext` stays off). | CODE | 1 hour | — |
| 3.4 | **Remove `localhost` from `WKAppBoundDomains`** in Release builds (simulator dev still needs it): a Release-only Run Script build phase that deletes the entry with PlistBuddy, plus a check that fails the archive if it is present. Also add `ITSAppUsesNonExemptEncryption = NO` to `Info.plist` (absent today) to skip the export question on every upload. | CODE | 2 hours | — |
| 3.5 | **Release signing.** Android: generate the upload keystore (owner types the passwords into `keytool`; Claude never sees them), add a `signingConfigs.release` reading a git-ignored `keystore.properties`, build an AAB (`bundleRelease`), enroll in Play App Signing on first upload. Back up the keystore and passwords in the owner's password manager; losing the upload key means a support reset. iOS: Xcode automatic signing with the team (2.6), archive → upload. Version scheme: `versionCode`/`CFBundleVersion` = increasing integer per upload. | CODE + OWNER-ONLY (keystore passwords) | half a day | 1.5, 1.6 |
| 3.6 | **Export / print gap**: CSV export and `window.print()` do nothing in the WebView. Recommended for v1: hide those buttons when `Capacitor.isNativePlatform()` and show "Available on the web". A dead button is an App Review 2.1 (completeness) risk; native file save/share (`@capacitor/filesystem` + `@capacitor/share`) can follow later. Stripe billing portal and Connect onboarding opening in the system browser are acceptable; mention them in review notes. | CODE | half a day | — |
| 3.7 | **Device pass on a real iPhone and Android phone** against production with a demo academy: native Google + Apple sign-in, push arriving and tap opening the right screen, Stripe Checkout returning to the app, coach offline attendance, account deletion end to end. | CODE (drive) + OWNER (phones) | 1 day | 2.x, 3.1–3.6 |
| 3.8 | Optional **M7 Fastlane** lanes for repeatable uploads (needs an App Store Connect API key and a Play service-account JSON; both are secrets the owner creates). Manual Xcode/Play uploads are fine for v1. | CODE + OWNER-ONLY (keys) | 1 day | 1.5, 1.6 |

Targets are already compliant: Android `targetSdkVersion 36` meets Play's rule from
2026-08-31 (new apps and updates must target API 36); iOS deployment target 15.0 meets
Apple's iOS 13 minimum from 2026-09-09.

## Phase 4 — Store listing assets and forms (can overlap Phase 3)

| # | Step | Who | Cost | Lead time | URL |
|---|---|---|---|---|---|
| 4.1 | Demo academy with fake families and classes on production, plus one reviewer login per persona (parent, coach). Never use real tenant data: local seed DBs are copies of real academies. | OWNER-ONLY (sets reviewer passwords); ASSISTANT-OK for seeding demo data via the admin UI | $0 | half a day | https://academy.courtmastr.com/admin |
| 4.2 | Screenshots: iPhone 6.9" 1320×2868 (1–10); iPad 13" 2064×2752 only if iPad stays on; Play phone 1080×1920 or 1080×2400 (2–8, 4+ for featuring); Play feature graphic 1024×500; Play icon 512×512 (export from `mobile/assets/icon-only.png`). | ASSISTANT-OK (Claude can capture from the simulator/emulator) | $0 | 1 day | — |
| 4.3 | Store icon decision: keep the house academy's yellow "B" or supply a product mark (then `pnpm assets`). | OWNER-ONLY (decision) | $0 | — | — |
| 4.4 | Listing text: name, subtitle (Apple, 30), short description (Play, 80), full description, keywords (Apple, 100), support URL (add a public `/support` page; 404 today, or use `/security`), marketing URL, privacy URL. | ASSISTANT-OK (draft and enter); owner reviews | $0 | 2 hours | — |
| 4.5 | Apple **App Privacy** ("nutrition label"): enter answers from store-listing doc §3; Tracking = No. | ASSISTANT-OK | $0 | 30 min | https://developer.apple.com/app-store/app-privacy-details/ |
| 4.6 | Play **Data safety** form, including the Data deletion section with the `/account-deletion` URL (after 3.1 D4 ships). | ASSISTANT-OK | $0 | 30 min | https://support.google.com/googleplay/android-developer/answer/10787469 |
| 4.7 | Age rating: Apple's 2026 questionnaire (not Kids category; messaging = yes); Play IARC questionnaire + Target audience **18 and over only** (any under-13 band pulls in the Families policy). | ASSISTANT-OK fills; OWNER-ONLY submits the IARC declaration | $0 | 30 min | App Store Connect → App Information; Play Console → App content |
| 4.8 | Play App content declarations: ads = none, app access (give the reviewer logins from 4.1), news = no, government = no, financial features = none (Stripe is checkout for services). | ASSISTANT-OK | $0 | 30 min | Play Console → Policy → App content |
| 4.9 | App Review notes (Apple) / app access instructions (Play): walk through sign-in → coach offline attendance → a push arriving; explain Stripe for real-world services; list what opens in the system browser. | ASSISTANT-OK (Claude drafts) | $0 | 1 hour | — |

## Phase 5 — Test tracks

| # | Step | Who | Cost | Lead time | URL |
|---|---|---|---|---|---|
| 5.1 | Create the app record in App Store Connect (name, bundle id, SKU, primary language). | ASSISTANT-OK | $0 | 10 min | https://appstoreconnect.apple.com/apps |
| 5.2 | Archive in Xcode (Release, after `pnpm sync:release`) and upload. | OWNER-ONLY (signing identity on the owner's Mac) or CODE once signed in | $0 | 30 min + processing ~15–60 min | Xcode → Product → Archive |
| 5.3 | TestFlight: internal testers (up to 100, no review) right away; external testers need a short Beta App Review (~1 day). Invite the owner + a coach + a parent. | ASSISTANT-OK | $0 | Same day / ~1 day | App Store Connect → TestFlight |
| 5.4 | Create the app in Play Console; upload the AAB to **Internal testing**; enroll in Play App Signing; then do step 2.5 (Play signing SHA-1 into Firebase) and re-test Google sign-in. | ASSISTANT-OK for console; upload needs the signed AAB from 3.5 | $0 | Internal track: minutes to hours | https://play.google.com/console |
| 5.5 | Run 3.7's device pass on the TestFlight and internal-test builds; fix; re-upload with a higher build number. | CODE + OWNER | $0 | 2–5 days | — |
| 5.6 | Only if the Play account ended up **personal**: closed test with **12+ testers opted in for 14 consecutive days** before production unlocks. | OWNER-ONLY (recruit testers) | $0 | +14 days minimum | https://support.google.com/googleplay/android-developer/answer/14151465 |

## Phase 6 — Submission

| # | Step | Who | Cost | Lead time | URL |
|---|---|---|---|---|---|
| 6.1 | Final read of listing, privacy answers, review notes and reviewer logins; confirm the reviewer accounts still work. | ASSISTANT-OK, owner signs off | $0 | 1 hour | — |
| 6.2 | Apple: attach the build to the version, choose manual release, **Submit for Review**. | OWNER-ONLY | $0 | Review usually 24–48 h; budget a second round for 4.2 | App Store Connect |
| 6.3 | Play: promote internal build to **Production** (staged rollout 20% recommended), **Send for review**. First review of a new developer's app can take up to ~7 days. | OWNER-ONLY | $0 | Hours to ~7 days | Play Console → Production |
| 6.4 | After approval: release; watch Sentry and Play vitals for crashes; future website deploys update the app without a store release (only native shell changes need one). | OWNER-ONLY (release button); ASSISTANT-OK (monitoring) | $0 | — | — |

## Owner runbook — every task RamC owns, step by step

Written so an AI assistant on RamC's computer can prepare each task and walk RamC through
it. In each task, **"Assistant"** lines are safe to hand over; **"You"** lines involve
money, identity, agreements, passwords or secret keys, so RamC does them personally
(the assistant can open the page and point at the field). Screen wording in the stores
changes often: if a label differs, look for the closest match, don't guess at legal fields.

Do them in this order. O1–O5 start the clock; everything else can happen while waiting.

### O1. Company fact sheet (do first, 15 min)

Every form below must use **identical** company details. One mismatch (an "LLC" missing,
"St" vs "Street") is the most common reason enrollment stalls.

- **Assistant:** create a note `Marvy Labs - store facts` (in your password manager or a
  private doc) and fill it from the LLC paperwork (Illinois Articles of Organization, or
  look the LLC up at https://apps.ilsos.gov/businessentitysearch/):
  - Legal name exactly as registered (e.g. `Marvy Labs LLC`)
  - Illinois file number, date formed, status (must say Active)
  - Registered business address (street, city, ZIP) — must be a real address, not a
    P.O. box
  - Business phone number you can answer during business hours
  - Website: `https://marvy-labs.com`
  - Work email on that domain (see O2)
  - Your legal first and last name as on your government ID, and your title (Owner /
    Managing Member)
  - D-U-N-S number (fill in after O3)
- **You:** check the note against the LLC paperwork. **Done when** every field is filled
  and matches.

### O2. A work email on marvy-labs.com (15 min)

Apple wants the enrollment email on the organization's domain. `marvy-labs.com` uses
Cloudflare Email Routing (forwarding only), which is enough to receive verification mail.

- **Assistant:** in Cloudflare (https://dash.cloudflare.com → marvy-labs.com → Email →
  Email Routing → Routing rules), add custom addresses `ramc@marvy-labs.com`,
  `support@marvy-labs.com` and `appstore@marvy-labs.com` forwarding to your Gmail. Send a
  test mail to each and confirm it arrives.
- **You:** sign in to Cloudflare if asked; click the confirmation link Cloudflare sends to
  your Gmail the first time.
- **Note:** forwarding cannot *send* from that address. That is fine for enrollment. If
  you want to reply as `support@`, set up Gmail "Send mail as" later.
- **Done when** all three addresses forward.

### O3. D-U-N-S number (10 min of work; wait up to 30 days — start today)

- **Assistant:** open https://developer.apple.com/enroll/duns-lookup/ , sign in with your
  Apple Account (O4; any existing one is fine for the lookup), and fill the form from O1:
  legal entity name, address, phone, your name, title and work email.
- **You:** review every field and press Submit.
- If Apple finds a match: it shows the D-U-N-S number. Check the name and address match
  O1 exactly. If the address is old, ask D&B to update it (https://www.dnb.com/duns.html
  → "Update your D-U-N-S record") and wait for the update before enrolling.
- If no match: submit the request. Apple says D&B usually emails within ~5 business days;
  D&B says up to 30. **Do not pay D&B** for an expedited number; it is free.
- D&B may phone or email to verify. Answer it.
- **Done when** you have the 9-digit number and it is in the O1 note.

### O4. Apple Account for the business (15 min)

- **Recommended:** a new Apple Account just for the business, using
  `appstore@marvy-labs.com`, so the developer account is not tied to your personal
  iCloud. (Your personal Apple Account also works if you prefer.)
- **You:** create it at https://account.apple.com → Create Your Apple Account. Use your
  **legal** first and last name (not "Marvy Labs" — company names in name fields delay
  approval). Turn on **two-factor authentication** with your phone number.
- **Assistant:** nothing; this is identity + password.
- **Done when** you can sign in to https://developer.apple.com/account with it and 2FA
  codes arrive on your phone.

### O5. Apple Developer Program enrollment (30 min; Apple review ~2 days–2 weeks; $99/yr)

Needs O3 (D-U-N-S) and O4.

- **You:** start at https://developer.apple.com/programs/enroll/ → Start your enrollment
  (or the Apple Developer app on your iPhone/Mac → Account → Enroll; if the app does not
  offer organization enrollment, use the web).
  1. Sign in with the O4 Apple Account.
  2. Entity type: **Company / Organization** (not Individual).
  3. Enter from O1: legal entity name, D-U-N-S number, your legal name, work email, phone,
     website `https://marvy-labs.com`, headquarters address.
  4. Confirm you have legal authority to bind Marvy Labs LLC (you are the owner).
  5. Submit. Apple emails an Enrollment ID — save it in the O1 note.
- **Wait.** Apple may phone the business number to confirm you work there and can sign
  agreements. Answer it. If nothing arrives in 2 weeks, contact
  https://developer.apple.com/contact/ with the Enrollment ID.
- **You:** when the approval email arrives, sign in, **accept the Apple Developer Program
  License Agreement**, and **pay $99** (card that can be charged in USD). Membership
  confirmation can take up to 24 hours.
- **Assistant afterwards:** check https://developer.apple.com/account shows "Apple
  Developer Program" with team name "Marvy Labs LLC" and copy the **Team ID** (10
  characters, Membership details) into the O1 note.
- **Not needed:** the Paid Apps agreement, tax forms and bank info. The app is free.
- **Done when** membership is active and the Team ID is saved.

### O6. Google Play Console organization account (30 min; checks take days; $25 once)

Needs O3 (D-U-N-S).

- **Recommended:** a Google Account for the business (e.g. a new Gmail
  `marvylabs.apps@gmail.com`, or a Google Workspace account) rather than your personal
  Gmail. The account email is not shown publicly.
- **You:**
  1. Go to https://play.google.com/console/signup and sign in with that Google Account.
  2. Choose **An organization or business** (not "Yourself"). This is what lets you skip
     the 14-day, 12-tester test personal accounts must run.
  3. Create or pick a **Google Payments profile**: type **Organization**, legal name and
     address **exactly** as in the D-U-N-S record (Google checks they match).
  4. Enter the D-U-N-S number, organization phone, website `https://marvy-labs.com`,
     organization size, and a contact name/email/phone.
  5. **Developer name** (shown on Google Play under the app): `Marvy Labs LLC` or
     `Marvy Labs`. **Developer email** shown publicly: `support@marvy-labs.com`.
  6. Verify the contact email, contact phone, developer email and developer phone with
     the one-time codes Google sends.
  7. Accept the **Developer Distribution Agreement**, pay **$25** (no prepaid cards).
  8. If asked, upload a government ID in your legal name.
- **Wait.** Payment verification can take up to 5 days; identity checks usually a few
  days. Watch the Play Console inbox and email.
- **Done when** Play Console shows the account verified and lets you "Create app".

### O7. Product decisions (30 min; write answers into the O1 note)

The assistant can prepare a one-page form with these; you choose.

| Decision | Recommendation | Why |
|---|---|---|
| Store app name (max 30) | e.g. `CourtMastr Academy` | "Academy" alone is generic and may be taken |
| Bundle / package id | keep `com.courtmastr.academy` | Permanent after first upload |
| Devices | **iPhone only** for v1 | iPad would need its own 13" screenshots |
| Countries | **United States only** for v1 | Avoids the EU trader-status declaration |
| Category | Education (Apple primary), Sports (secondary); Play: Education | |
| Icon | keep the yellow "B" or supply a new 1024×1024 mark | Changing later is easy; changing the name is not |
| Support email | `support@marvy-labs.com` | Matches the seller and website |

### O8. Account-deletion decisions (1 hour) and privacy review (1–2 weeks)

Claude cannot build the required in-app deletion until these are answered. Recommended
answers in **bold**; detail in `docs/plans/2026-11-03-account-deletion.md`.

1. Keep invoices/payments 7 years? **Yes; keep the payer name on kept invoices.**
2. Children's records when a parent deletes: **keep anonymised rows ("Student 4F2A") for
   academy stats; delete names, date of birth, medical notes.**
3. Another guardian still has an account: **children stay with that guardian.**
4. Signed waivers: **keep, visible to the academy owner only; ask counsel how long.**
5. Messages the person wrote: **redact the text, show "Deleted user".** (Apple counts
   user content as part of deletion unless the law requires keeping it.)
6. Stripe customer: **keep it with cards removed, for refunds/disputes.**
7. Unpaid balance: **allow deletion, notify the academy admin.**
8. Coach still assigned to sessions: **allow, alert the admin to reassign.**
9. Grace period: **14 days, undo only by contacting the academy.**
10. Audit logs that copied name/email/phone: **redact those fields.**
11. Support contact and controller: **`support@marvy-labs.com`; Marvy Labs LLC is the
    controller for account data, each academy for its families' data.**

- **You:** reply to Claude with "accept all recommendations" or your changes.
- **You:** after Claude rewrites the privacy policy (slice D5), send it to a lawyer for
  review. Only then remove the "Draft" banner. Cost varies; budget up to ~$1,500.

### O9. Apple key for push and Sign in with Apple (15 min; after O5)

The key file is a secret: downloadable **once**, never commit it, never paste it in chat.

- **Assistant:** after O5, register the App ID first (Identifiers → + → App IDs → App →
  Bundle ID explicit `com.courtmastr.academy`; capabilities: **Push Notifications**,
  **Sign In with Apple**).
- **You:**
  1. https://developer.apple.com/account/resources/authkeys/list → **+**. Name
     `CourtMastr push and SIWA`. Tick **Apple Push Notifications service (APNs)** and
     **Sign in with Apple** (Configure → choose the App ID). Continue → Register.
  2. **Download** the `.p8` file. Store it in your password manager along with the
     **Key ID** shown on the page and the **Team ID** (O5).
  3. Firebase console → project → ⚙ Project settings → **Cloud Messaging** → Apple app
     configuration → APNs Authentication Key → Upload: the `.p8`, Key ID, Team ID.
     (Needs the iOS app from step 2.1 registered first; the assistant can do 2.1.)
  4. Firebase → **Authentication → Sign-in method → Apple** → Enable. In the OAuth code
     flow section enter Team ID, Key ID and the key contents. Save.
- **Done when** Firebase shows the APNs key uploaded and Apple sign-in enabled.

### O10. Sign in to Xcode (5 min; after O5)

- **You:** open Xcode → Settings → Accounts → **+** → Apple Account → sign in with the O4
  account. Then tell Claude; it selects the team on the App target and confirms Push
  Notifications and Sign in with Apple show under Signing & Capabilities.

### O11. Android upload key (10 min; when Claude reaches release signing)

- **Claude** gives you one Terminal command (`keytool -genkeypair …`) and the file path.
- **You:** run it in Terminal and type a strong password when asked (Claude never sees
  it). Save the `.jks` file **and** the password in your password manager, plus an
  offline backup. Losing it means a Google support reset before you can update the app.
- **You:** put the password in the git-ignored `mobile/android/keystore.properties` file
  Claude creates (Claude leaves the password field blank for you).

### O12. Reviewer demo accounts (30 min; before submission)

- **Assistant:** create a demo academy on production with fake classes and fake
  families through the admin UI (never copy a real family).
- **You:** create one parent and one coach login for the reviewers with passwords you
  choose; save them in your password manager. Give them to the assistant only to paste
  into the store "App Review / App access" fields.

### O13. Approvals and final buttons (each a few minutes)

- **You:** approve each Claude PR before merge, and each push.
- **You:** press the final submit on Google's content-rating (IARC) questionnaire after
  the assistant fills it.
- **You:** Apple: App Store Connect → the version → **Add for Review → Submit**.
  Choose **Manually release** so you control the launch day.
- **You:** Google: Production → create release with the tested build → staged rollout
  20% → **Send for review**.
- After approval: press **Release** in each store.

## Prompt for the owner's AI assistant (ASSISTANT-OK steps)

Hand this to the assistant after signing in to Apple Developer, App Store Connect,
Firebase and Play Console yourself.

```text
You are helping publish the CourtMastr Academy mobile app (bundle id com.courtmastr.academy)
to the App Store and Google Play. I am already signed in to every console you need.

Hard limits — stop and hand control back to me instead of doing any of these:
- paying, entering card or bank details, or accepting any agreement or terms;
- entering, creating, viewing or downloading passwords, private keys (.p8, keystores,
  service-account JSON) or API keys;
- pressing "Submit for Review", "Send for review", "Release" or any IARC/content-rating
  final submit;
- creating user accounts or setting their passwords;
- uploading anything other than the screenshots and graphics I give you.
Never put real family, student or payment data into a listing or screenshot.

Do these, in order, and report what you did with a screenshot of each finished page:
1. Firebase console (project already exists): add an iOS app and an Android app with bundle
   id com.courtmastr.academy; download GoogleService-Info.plist and google-services.json to
   ~/Downloads and tell me their paths.
2. Apple Developer > Identifiers: register App ID com.courtmastr.academy with
   Sign in with Apple and Push Notifications enabled.
3. App Store Connect > Apps: create the app record (name: <STORE NAME>, primary language
   English (U.S.), SKU courtmastr-academy, bundle id com.courtmastr.academy). Set
   availability to United States only.
4. Fill the App Store listing text, App Privacy answers and age-rating questionnaire using
   docs/plans/2026-11-03-store-listing.md sections 1, 3 and 4 (I will paste it). Tracking: No.
   Do not choose the Kids category.
5. Play Console: create the app (free, app not game), then complete App content:
   privacy policy URL https://academy.courtmastr.com/privacy, ads = none,
   app access = use the reviewer logins I give you, target audience = 18 and over only,
   Data safety from section 3 of the same doc, data deletion URL
   https://academy.courtmastr.com/account-deletion. Fill the content-rating questionnaire
   but leave the final submit to me.
6. Add the main store listing text and upload the screenshots, 512x512 icon and 1024x500
   feature graphic I provide.
7. TestFlight: add the internal testers I list. Play Console > Internal testing: add the
   tester emails I list.
List anything that asked for information you did not have.
```

## Sources (checked 2026-11-03)

- Apple organization enrollment ($99/yr, D-U-N-S, legal entity, website, domain email):
  https://developer.apple.com/programs/enroll/
- Apple upcoming requirements (Xcode 26 / iOS 26 SDK from 2026-04-28; iOS 13 minimum from
  2026-09-09; age-rating questionnaire; EU trader status): https://developer.apple.com/news/upcoming-requirements/
- Apple account deletion (5.1.1(v), in-app initiation, Sign in with Apple token
  revocation, retention allowed if disclosed): https://developer.apple.com/support/offering-account-deletion-in-your-app/
- App Review Guidelines (4.2, 4.8, 3.1.3(e)): https://developer.apple.com/app-store/review/guidelines/
- Google Play organization account (D-U-N-S required, up to 30 days; Payments profile
  must match D&B; payment check up to 5 days): https://support.google.com/googleplay/android-developer/answer/13628312
- Play testing rule for personal accounts created after 2023-11-13 (12 testers, 14
  days): https://support.google.com/googleplay/android-developer/answer/14151465
- Play target API (API 36 for new apps and updates from 2026-08-31):
  https://developer.android.com/google/play/requirements/target-sdk
- Play account deletion (in-app path + web link in Data safety):
  https://support.google.com/googleplay/android-developer/answer/13327111
- Live checks: `marvy-labs.com` is live (Cloudflare, Email Routing MX); `marvylabs.com`
  (no hyphen, the app's current support domain) has MX but no website; `academy.courtmastr.com/privacy`
  shows the draft banner; `/account-deletion` and `/support` return 404.
