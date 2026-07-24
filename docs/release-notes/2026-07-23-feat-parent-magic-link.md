# feat-parent-magic-link

PR: #332

## What changed
The parent daily practice digest now signs provisioned-but-never-activated
parents straight into the portal with a one-time magic link, instead of dropping
them on the sign-in page.

Previously the Variant B activation CTA linked to `/login` (the 404 fix that
preceded this). That still required the parent to remember/reset a password.
Now, when the digest is built for a parent who has never activated their
account, the composition root mints a single-use token and the CTA points at
`/auth/magic?t=<token>`. Tapping it exchanges the token for a Firebase session
and lands the parent on the right page — `/parent/payments` when a balance is
owed, otherwise `/parent/dashboard`.

New pieces:

- **Domain errors** `MagicLinkInvalid` (401) and `MagicLinkExpired` (410).
- **Use cases** `IssueMagicLink` / `ConsumeMagicLink` (identity context). Only
  `sha256(token)` is stored; tokens are issued with `secrets.token_urlsafe(32)`.
- **Mongo repo** on `parent_magic_links` with an atomic, single-use
  `mark_used` (conditional `used_at=None` update).
- **Firebase adapter** gains `create_custom_token(uid)`.
- **Migration 0149** — unique index on `token_hash`, TTL index on `purge_at`.
- **Public route** `POST /api/v2/magic-link/consume` returning
  `{custom_token, next_path}`.
- **Frontend route** `/auth/magic` that consumes the token, calls
  `signInWithCustomToken`, and redirects.

## Security
The emailed token is a bearer credential, so it is deliberately hardened and
these properties must not be weakened:

- **Single-use + race-safe** — redemption is an atomic conditional update; a
  replay (or the loser of a concurrent race) gets 401.
- **Short-lived** — 72h TTL (410 after that); rows self-purge 7 days later via
  the TTL index.
- **POST-only consume** — mail-scanner GET prefetches cannot burn a token.
- **Tenant-bound** — a token issued for one academy is rejected against another;
  the tenant is resolved from the request host, never inferred.
- **Open-redirect-safe** — `next_path` must be a same-site absolute path
  (`//host` and absolute URLs collapse to the dashboard), enforced on both
  issue and consume, and again client-side before redirect.

Minting is best-effort: any failure in the digest falls back to the `/login`
CTA, so a digest never crashes on this.

## Deploy notes
Runs migration `0149_parent_magic_link_indexes` on boot (creates the
`parent_magic_links` unique + TTL indexes). No config changes. Takes effect on
the next daily digest send.

## Risk / rollback
Low blast radius. The new consume route and `/auth/magic` page are additive; no
existing route or auth path changes. The digest's Variant B CTA is the only
behavioural change, and token minting is wrapped in try/except so any failure
degrades to the previous `/login` CTA — the digest cannot crash on this.

To roll back, revert this PR: the digest returns to linking `/login`, and the
unused `parent_magic_links` collection self-empties via its TTL index (no data
migration needed). The additive `0149` indexes are harmless if left in place.

