# fix-digest-activate-url-404

PR: #TBD

## What changed
The activation button in the parent daily practice digest email ("Create my
account" / "Set up account & pay") pointed at
`/parent/login?continue=/parent/payments` — a route that does not exist in the
frontend — so every parent who tapped it landed on the 404 page. It now links
to `/login`, with the parent's email prefilled.

These parents are already in the system: admin provisioning creates their
Firebase account, they simply never set a password. Sign-in (then "Forgot
password" for a set-password link) is the correct destination; public signup
would collide with `auth/email-already-in-use`.

## Deploy notes
None. Backend-only change; takes effect on the next daily digest send.
