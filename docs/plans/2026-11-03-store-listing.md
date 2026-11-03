# App Store and Google Play compliance checklist (mobile slice M6)

Status: checklist, derived from the code on 2026-11-03. Owner actions are marked **[owner]**.
Parent plan: `docs/plans/2026-11-02-mobile-apps.md`. Deletion: `docs/plans/2026-11-03-account-deletion.md`.

Store-side answers below describe what the app does **today**; re-check them when a slice
adds a data type (push tokens arrive with M4).

## 1. Identity and listing basics

| Item | Today | Action |
|---|---|---|
| Legal entity / seller | `frontend/lib/brand.ts`: company "Marvy Labs", product "CourtMastr", support `support@marvylabs.com` | **[owner]** confirm the publishing entity matches the developer accounts (organization account + D-U-N-S) |
| App name | `capacitor.config.ts` `appName: "Academy"`; PWA manifest says "CourtMastr" | **[owner]** pick the store name (30 chars Apple, 30 Google); "Academy" alone is too generic to be findable or approved as a unique name |
| Bundle / package id | `com.courtmastr.academy` | **[owner]** confirm; permanent after first upload |
| Icon | `mobile/assets/` → generated (commit "app icon and splash screens"); the mark is the house academy's yellow "B" | **[owner]** keep the "B", or supply a product mark and rerun `pnpm assets`. Store icons: Apple 1024×1024 is in the asset catalog; Google 512×512 PNG upload — export from `mobile/assets/icon-only.png` |
| Category | — | Apple: Education (primary), Sports (secondary). Google: Education or Sports |
| Support URL | none dedicated | Use `https://academy.courtmastr.com/security` or add a `/support` page; must be reachable without sign-in |
| Marketing URL | `https://academy.courtmastr.com` | Optional |

## 2. Privacy policy and terms URLs

- `/privacy` and `/terms` exist (`frontend/app/(marketing)/privacy`, `/terms`) and are
  public (not in the `middleware.ts` matcher). Use
  `https://academy.courtmastr.com/privacy` and `.../terms` (the product host; tenant
  hosts only rewrite `/`).
- **The privacy page is not store-ready.** It carries a "Draft privacy summary. Review
  with counsel" banner and is generic. Both stores reject policies that do not match
  the data-safety answers. It must state, at minimum:
  - every data type in section 3 below, including children's data entered by parents
    (name, date of birth, medical notes) and that the academy, not the child, enters it;
  - the processors: Firebase/Google (auth, push), Stripe (payments), Resend (email),
    Sentry (errors), Fly.io and Cloudflare (hosting), MongoDB Atlas (database);
  - retention (financial and audit records 7 years, per `RetentionPolicy`);
  - how to delete an account in the app and on the web (`/account-deletion`, deletion
    slice D4), and what is kept after deletion;
  - the controller and contact. Each academy decides what it collects about its
    families, so Marvy Labs is likely a processor for academy data and controller for
    account data. **[owner, with counsel]**
- **[owner]** remove the draft banner only after counsel review. Also add `/privacy`,
  `/terms` to `app/sitemap.xml` (they are not listed).

## 3. What the app collects (source for both forms)

Derived from the code: Firebase Auth (`frontend/lib/auth`), Stripe Checkout and saved
payment methods (`parent_billing_customers` stores card brand/last4), Sentry
(`frontend/lib/observability/sentry.ts`, backend `shared/observability/errors.py`:
`sendDefaultPii: false`, user id only, 20% performance tracing), parent forms
(`frontend/lib/api/parent.ts`), messages, waivers (`ip_address`, `user_agent`,
signature name). No ads SDK, no analytics SDK, no cross-app tracking, no location, no
contacts, no camera. Photo upload exists only in admin settings (academy logo/photos).

| Data | Who | Purpose | Linked to user |
|---|---|---|---|
| Name, email, phone | parents, coaches, admins | Account, app functionality, transactional email | Yes |
| Child name, date of birth | entered by parent/admin | App functionality (enrollment, age groups) | Yes |
| Child medical notes | entered by parent | App functionality (coach safety) | Yes |
| Payment info (card via Stripe; brand + last 4 stored) | parents | Payments | Yes |
| Purchase history (invoices, payments) | parents | App functionality, accounting | Yes |
| Messages (parent–coach), absence notes | parents, coaches | App functionality | Yes |
| Waiver signature (typed name, IP address, user agent) | parents | Legal record | Yes |
| User ID (Firebase uid) | all | Auth, error reports | Yes |
| Crash and performance data (Sentry) | all | Diagnostics | Yes (user id) |
| Push token (from M4) | all who allow push | Notifications | Yes |
| Photos (logo/academy photos) | admins only | App functionality | Yes |

### Apple App Privacy ("nutrition label")

Tracking: **No** (no data used for tracking; no ATT prompt needed).

Data Linked to You, all with purpose **App Functionality** unless noted:
- Contact Info: Name, Email Address, Phone Number
- Health & Fitness: Health (child medical notes)
- Financial Info: Payment Info (Stripe Checkout, saved card brand and last 4)
- Purchases: Purchase History
- User Content: Other User Content (messages, absence notes, waiver signatures); Photos or
  Videos (admin uploads)
- Identifiers: User ID; Device ID once M4 ships (push token)
- Other Data: child date of birth (Apple has no "date of birth" type; declare under
  Other Data Types)
- Diagnostics: Crash Data, Performance Data (purpose: App Functionality; Sentry is
  used to fix faults, not for product analytics)

Data Not Linked to You: none. Data Used to Track You: none.

Privacy manifest: Capacitor ships its own `PrivacyInfo.xcprivacy` in the framework; the
app target has none. The shell calls no required-reason API itself, so none is needed
until a native plugin that does is added (check each new plugin).

### Google Play data safety

- Data collected: Personal info (Name, Email address, Phone number, Other info = child
  date of birth), Financial info (User payment info, Purchase history), Health and
  fitness (Health info), Messages (Other in-app messages), Photos (admins), App info
  and performance (Crash logs, Diagnostics), Device or other IDs (push token, from M4).
- Data shared: **No** (transfers to service providers acting for us are not "sharing"
  under Play's definition).
- Collection required: account data and payments are required; medical notes, messages
  and push are optional.
- Encrypted in transit: **Yes** (HTTPS only; the release build must not set `cleartext`,
  which `capacitor.config.ts` enables only for an `http://` dev server).
- Users can request deletion: **Yes**, only after deletion slices D1–D4 ship; give the
  `/account-deletion` URL.

## 4. Age rating and audience

Users are parents, coaches and academy staff, all adults. Children are the *subject* of
the data, entered by adults; they do not sign in (student login is behind
`ENABLE_STUDENT_LOGIN`, which is `"false"` in `backend/fly.toml`). Not a Kids-category
app.

- **Apple**: do not select the Kids category. Age-rating questionnaire answers: no
  violence, sexual content, gambling, drugs, or profanity; no unrestricted web access
  (the webview is limited to App-Bound Domains); **messaging: yes**, private between
  parents and the academy's staff, not public user-generated content. Expect the lowest
  or near-lowest rating; record whatever App Store Connect computes.
- **Google**: Target audience and content = **18 and over** only. Choosing any band
  under 13 pulls the app into the Families policy (teacher-approved SDK rules, no
  personal data from children). IARC questionnaire: same answers as Apple, plus "users
  can interact" = yes (messaging), "shares location" = no, "digital purchases" = no.
- **If student login is ever enabled** in the app, this section must be redone: a
  student persona under 13 changes both stores' answers and triggers COPPA work.

## 5. Payments (Apple 3.1, Google Payments policy)

Classes, camps and lessons are services consumed outside the app, so Stripe is allowed
instead of in-app purchase (Apple 3.1.3(e) and 3.1.5(a); Play exempts physical goods and
services). Nothing sold unlocks digital content in the app. Keep it that way: a paid
in-app feature (for example a paid video library) would require IAP. Mention this in the
App Review notes so the reviewer does not flag Stripe Checkout.

## 6. Screenshots and graphics

Apple (App Store Connect, 2026 rules: the largest size is required, smaller sizes scale
down):
- iPhone 6.9" **1320×2868** or 1290×2796 portrait, 1 to 10 images. Required.
- iPad 13" **2064×2752** or 2048×2732, required **because the shell supports iPad**
  (`TARGETED_DEVICE_FAMILY = "1,2"` in the Xcode project). **[owner]** either supply iPad
  screenshots or switch to iPhone-only before the first upload (the app then still runs on
  iPad in compatibility mode).
- Optional app preview video, 15 to 30 seconds.

Google Play:
- Phone screenshots: 2 to 8, 16:9 or 9:16, each side 320 to 3840 px; 1080×1920 or
  1080×2400 is safe. At least 4 at 1080 px+ for featuring eligibility.
- Feature graphic **1024×500** (required).
- App icon **512×512** PNG, 32-bit (required).
- 7" and 10" tablet screenshots optional.

Screenshots must show the real app with demo data, never a real family's data (local
seed DBs are real tenant copies, so use a demo academy). **[owner]**

## 7. Apple 4.2 (minimum functionality) risk

The shell loads the website. Apple rejects apps that are "a repackaged website" without
app-like value. What we have and what is planned:

| Native capability | State | Weight with review |
|---|---|---|
| Native Google sign-in, Sign in with Apple (M1) | Code done, not device-tested | Moderate. Also required: 4.8 needs Sign in with Apple when Google sign-in is offered, which M1 does |
| Push notifications (M3/M4) | Backend M2 built locally; sending and app side not built | **Strongest argument.** Ship M4 before the first submission |
| Offline coach attendance (service worker under App-Bound Domains) | Configured, not device-tested | Good if it works on device; mention it in review notes |
| Account deletion in app (M5) | Designed | Required, not differentiating |

Risk: **medium-high if submitted before push works**, moderate after. Mitigations, in
order: submit only with M4 live; write review notes that walk through sign-in → coach
offline attendance → a push arriving; give the reviewer a demo login per persona
(parent and coach) on a demo academy with seeded classes **[owner]**; make sure no
screen shows web chrome (browser-style footers, "open in browser" links, the marketing
landing). Google Play has no equivalent rule but rejects broken webviews, so the same
device test covers it.

## 8. Other submission blockers seen in the code

- `capacitor.config.ts` defaults `server.url` to `http://localhost:3001` and sets
  `cleartext` for http. The release build must be synced with
  `MOBILE_SERVER_URL=https://academy.courtmastr.com` (M7 pipeline should enforce it).
- `WKAppBoundDomains` lists `localhost`; drop it from the release Info.plist.
- Firebase `GoogleService-Info.plist` / `google-services.json` are not in the repo yet
  (M1 owner step).
- Export compliance: the app uses only standard HTTPS encryption, so set
  `ITSAppUsesNonExemptEncryption = NO` in Info.plist to skip the per-build question.

## 9. Owner click list

1. Confirm legal entity, store name, bundle id (section 1).
2. Get the privacy policy reviewed and published without the draft banner (section 2).
3. Decide iPhone-only vs iPad (section 6).
4. Fill App Privacy and Data safety from section 3 when the deletion slices ship.
5. Apple: no Kids category; Google: target audience 18+ (section 4).
6. Produce screenshots on a demo academy; feature graphic 1024×500 (section 6).
7. Create demo reviewer logins and write review notes (section 7).
