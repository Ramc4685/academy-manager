# mobile-sign-in-entry

PR: #1091

## What changed
Returning parents, coaches and admins can find Sign in on a phone again. The app sets `viewport-fit=cover` with a translucent iOS status bar, so pages draw under the clock and battery. The public academy page's sticky header had no top inset, so its brand row and its "Parent login" link (visible at every width) sat under the status bar, where it was blurred and could not be tapped. The header now pads by `env(safe-area-inset-top)`. The link is now an outlined "Sign in" button (44px tall) that stays on screen while scrolling and sits next to the brand "Book a free trial" button without competing with it.

The same top inset now applies to every other public screen: the CourtMastr landing page, Privacy/Terms/Security (their nav links are now 44px targets), login, register, the email-action and magic-link screens, and unsubscribe. Each of those already linked to sign in. A source guard in `app/shell-safe-area.test.ts` and a 390px e2e check on the public page keep it that way.

## Deploy notes
Frontend only. No migrations, no backend change, no new routes. After deploy, open the BLNO public page on an iPhone and check that Sign in shows below the status bar.

## Risk / rollback
Low: CSS padding plus one link label. Desktop and Android, where the inset is 0, look the same as before apart from the outlined Sign in. Roll back by reverting the PR.
