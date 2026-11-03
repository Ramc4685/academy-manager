# Brief for RamC's AI assistant: set up the business and developer accounts

Hand this whole file to the assistant. It is self-contained.

## 1. Background

- **Who:** RamC Venkatasamy owns **Marvy Labs LLC**, a registered limited liability
  company. Its website is **https://marvy-labs.com** (live; email for the domain runs
  through Cloudflare Email Routing).
- **What:** Marvy Labs is about to publish a mobile app, **CourtMastr Academy**, to the
  Apple App Store and Google Play. The app is free. Sports academies use it to manage
  classes, attendance and billing, and parents and coaches sign in to it. The app itself
  is being built separately; it is **not** your job.
- **Your job:** get the **company-level legal and identity setup** done so that Marvy
  Labs LLC can publish apps:
  1. a company fact sheet,
  2. email addresses on the company domain,
  3. a D-U-N-S number for the LLC,
  4. a business Apple Account,
  5. an Apple Developer Program membership as an **organization**,
  6. a Google Play Console developer account as an **organization**.
- **Out of scope for now:** app name, icon, store listings, screenshots, privacy forms,
  Firebase, keys and certificates, uploading builds. Do not start any of those, even if a
  console offers a "Create app" button. RamC will decide those later.
- **Why "organization", not "individual/personal":** the store listing then shows
  "Marvy Labs LLC" as the seller instead of RamC's personal name, and Google skips a
  rule that makes new personal accounts run a 14-day test with 12 testers before they
  can publish.

## 2. Rules for you

You have access to RamC's computer. Even so, **stop and hand control to RamC** for:

- paying anything or entering card or bank details;
- accepting any agreement, license or terms of service;
- creating or typing passwords, and approving two-factor codes;
- uploading or photographing a government ID;
- the final **Submit** on the D-U-N-S request, the Apple enrollment and the Google
  sign-up (fill the form, then let RamC check it and press Submit);
- answering phone calls from Apple, Google or Dun & Bradstreet (tell RamC to expect them).

Also:
- **Never guess a legal field.** If a value is not in the fact sheet, ask RamC.
- Copy company details **character for character** from the fact sheet. A mismatch
  between forms ("LLC" missing, "St" vs "Street", an old address) is the most common
  reason enrollment stalls for weeks.
- Never pay Dun & Bradstreet for anything. The D-U-N-S number is free.
- Save every confirmation number, enrollment ID and email you receive into the fact sheet.
- Store the fact sheet somewhere private (RamC's password manager or a private note), not
  in a shared or public document.

## 3. Tasks, in order

Tasks A–C can be done today. D–E wait on the D-U-N-S number from task C.

### Task A — Company fact sheet (about 15 minutes)

Create a private note titled **"Marvy Labs - store facts"** and fill it in. Sources: the
LLC's Illinois Articles of Organization (ask RamC where they are) and the Illinois
business entity search at https://apps.ilsos.gov/businessentitysearch/ (search
"Marvy Labs").

| Field | Value |
|---|---|
| Legal entity name, exactly as registered | |
| State and file number | Illinois, |
| Status on the state site (must be **Active**) | |
| Date formed | |
| Business street address (no P.O. box) | |
| Business phone RamC answers during business hours | |
| Website | https://marvy-labs.com |
| Work email (from task B) | |
| RamC's legal first and last name, exactly as on his government ID | |
| RamC's title | Owner / Managing Member (confirm) |
| D-U-N-S number (from task C) | |
| Apple Enrollment ID (task E) | |
| Apple Team ID (task E) | |
| Google Play developer account ID (task F) | |

If the state site shows the LLC as anything other than **Active** (for example, an
annual report is overdue), stop and tell RamC. Apple and Google both verify against
public records.

**Done when** RamC has checked every field against the LLC paperwork.

### Task B — Email addresses on marvy-labs.com (about 15 minutes)

Apple wants the enrollment email on the company's own domain. The domain uses Cloudflare
Email Routing, which forwards mail but does not host mailboxes. Forwarding is enough to
receive verification emails.

1. Go to https://dash.cloudflare.com → **marvy-labs.com** → **Email** → **Email
   Routing** → **Routing rules**. RamC signs in if asked.
2. Create three custom addresses, each forwarding to RamC's Gmail:
   - `ramc@marvy-labs.com` (RamC's work email for enrollment forms)
   - `appstore@marvy-labs.com` (login for the business Apple Account)
   - `support@marvy-labs.com` (public support contact on the store listings)
3. If Cloudflare asks to verify the Gmail destination, RamC clicks the link in Gmail.
4. Send a test email to each address and confirm it arrives in Gmail.
5. Put `ramc@marvy-labs.com` in the fact sheet as the work email.

Note: these addresses can receive but not send. That is fine for now.

**Done when** all three test emails arrived.

### Task C — D-U-N-S number (about 10 minutes of work; wait up to 30 days)

A D-U-N-S number is a free 9-digit company ID from Dun & Bradstreet. Apple and Google
both require it for organization accounts. **Start this first; it is the longest wait.**

1. Open https://developer.apple.com/enroll/duns-lookup/ . It asks for an Apple Account
   sign-in; any Apple Account works for the lookup. If task D is not done yet, RamC can
   use his personal one here.
2. Fill the form from the fact sheet: legal entity name, headquarters address, phone,
   RamC's name, title and work email (`ramc@marvy-labs.com`).
3. Let RamC review every field. **RamC presses Submit.**
4. Outcomes:
   - **Match found:** the page shows a D-U-N-S number. Check its name and address
     against the fact sheet. If they match, save the number; you are done. If the D&B
     record has an old or wrong address, tell RamC; the record must be corrected at
     https://www.dnb.com/duns.html before tasks E and F, and that takes days.
   - **No match:** submit the request. D&B usually emails the number within about
     5 business days (it can take up to 30). D&B may phone or email RamC to verify the
     business; tell him to answer.
5. If D&B emails an offer to pay for faster processing, ignore it.
6. Save the number in the fact sheet.

**Done when** the 9-digit number is in the fact sheet and its record matches the
company name and address exactly.

### Task D — Business Apple Account (about 15 minutes)

A separate Apple Account for the business keeps the developer account off RamC's
personal iCloud.

1. Go to https://account.apple.com → **Create Your Apple Account**.
2. Email: `appstore@marvy-labs.com`.
3. First and last name: **RamC's legal first and last name**. Do **not** put "Marvy
   Labs" in the name fields; Apple delays approval when a company name is there.
4. **RamC chooses and types the password** and saves it in his password manager.
5. Phone number for two-factor authentication: RamC's mobile. Two-factor **must** be on.
6. Confirm the verification code sent to `appstore@marvy-labs.com` (it forwards to Gmail).
7. Check that signing in at https://developer.apple.com/account works and asks for a
   two-factor code on RamC's phone.

**Done when** RamC can sign in to developer.apple.com with this account.

### Task E — Apple Developer Program, as an organization ($99/year; Apple review about 2 days to 2 weeks)

Needs the D-U-N-S number (task C) and the Apple Account (task D).

1. Go to https://developer.apple.com/programs/enroll/ → **Start your enrollment**.
   Sign in with `appstore@marvy-labs.com`.
2. Entity type: **Company / Organization**. Not Individual / Sole Proprietor.
3. Fill from the fact sheet:
   - legal entity name: exactly as on the D-U-N-S record;
   - D-U-N-S number;
   - headquarters address and phone;
   - website: `https://marvy-labs.com`;
   - RamC's legal name, work email `ramc@marvy-labs.com`, and phone;
   - confirm RamC has legal authority to bind the company (he is the owner).
4. RamC reviews and **presses Submit**. Save the **Enrollment ID** from the screen or
   confirmation email in the fact sheet.
5. **Wait.** Apple checks the details against D&B. Apple may phone the business number to
   confirm RamC's role; RamC answers. Apple may ask for business documents (for example
   the Articles of Organization); ask RamC for them.
6. When Apple's approval email arrives: RamC signs in, **accepts the Apple Developer
   Program License Agreement** and **pays $99** with a card that can be charged in USD.
   Membership confirmation can take up to 24 hours.
7. Afterwards, open https://developer.apple.com/account → **Membership details** and
   check: program "Apple Developer Program", entity "Marvy Labs LLC", status active.
   Copy the **Team ID** (10 characters) into the fact sheet.
8. If nothing has happened 14 days after submitting, open a request at
   https://developer.apple.com/contact/ and quote the Enrollment ID.

Do **not** set up the Paid Apps agreement, tax forms or bank account in App Store
Connect; the app is free and does not need them.

**Done when** membership is active and the Team ID is in the fact sheet.

### Task F — Google Play Console, as an organization ($25 once; checks take a few days)

Needs the D-U-N-S number (task C).

1. **Google Account to own it.** Recommended: a new Google Account for the business (for
   example a new Gmail such as `marvylabs.apps@gmail.com`), rather than RamC's personal
   Gmail. RamC creates it and sets the password and two-step verification. The account
   email is not shown publicly.
2. Go to https://play.google.com/console/signup and sign in with that account.
3. Account type: **An organization or a business**. Not "Yourself".
4. **Google payments profile:** create a new one of type **Organization / Business**.
   Legal name and address must match the D-U-N-S record **exactly**; Google compares them
   and may restrict the account if they differ.
5. Organization details, from the fact sheet: D-U-N-S number, organization phone,
   website `https://marvy-labs.com`, organization size, contact name, email and phone.
6. Public developer details (shown on Google Play):
   - developer name: `Marvy Labs LLC` (confirm with RamC);
   - developer email: `support@marvy-labs.com`;
   - developer phone: the business phone.
7. Google sends one-time codes to the contact email, contact phone, developer email and
   developer phone. Enter each; RamC reads the codes from his phone and Gmail.
8. RamC reviews, **accepts the Google Play Developer Distribution Agreement** and **pays
   $25** (Visa, Mastercard, Amex or Discover; no prepaid cards).
9. If Google asks for identity verification, **RamC uploads his government ID himself.**
10. **Wait.** Payment verification can take up to 5 days and identity checks a few days.
    Check the Play Console inbox and the Google Account's Gmail daily.
11. Save the developer account ID (Play Console → Settings → Developer account) in the
    fact sheet.

Do **not** click "Create app" yet.

**Done when** Play Console shows the account as verified.

## 4. Report back to RamC after each task

After each task, send RamC a short message with:
- what was done, plus a screenshot of the final confirmation page;
- every ID or number received (already saved in the fact sheet);
- what is waiting on someone else, and the date to check again;
- anything you could not do, and what you need from RamC.

## 5. Common problems

| Problem | What to do |
|---|---|
| Apple says the name doesn't match D&B | Fix the D&B record (https://www.dnb.com/duns.html) so it matches the state registration, wait for the update, then retry. Don't change the Apple form to match a wrong D&B record. |
| Apple rejects the website | Check that https://marvy-labs.com loads, names Marvy Labs, and shows contact info. Tell RamC if any page is a placeholder. |
| Apple asks for "legal binding authority" proof | RamC is the owner. If Apple asks for a document, ask RamC for the Articles of Organization. |
| Google says the payments profile doesn't match | The payments profile name and address must equal the D&B record. Edit the payments profile, not the D&B record, unless D&B is wrong. |
| A verification email never arrives | Check Gmail spam, then check the Cloudflare routing rule from task B. |
| Something asks for payment, a password, an agreement or an ID | Stop and hand to RamC (section 2). |

## 6. Cost and time summary

| Item | Cost | Typical wait |
|---|---|---|
| Fact sheet, email addresses, Apple Account | $0 | Same day |
| D-U-N-S number | $0 | ~5 business days, up to 30 |
| Apple Developer Program | $99 per year | ~2 days to 2 weeks after submitting |
| Google Play Console | $25 once | A few days |

When all six tasks are done, tell RamC. The next phase (app records, Firebase, keys,
store listings) uses the full checklist in
`docs/plans/2026-11-03-publish-checklist.md`.
