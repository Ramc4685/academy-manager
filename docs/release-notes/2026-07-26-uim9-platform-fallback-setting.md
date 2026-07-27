# uim9-platform-fallback-setting

PR: #352

## What changed
Admin Settings → Gateway now shows a "Platform charge fallback" card with the
current on/off state and a confirm-with-reason dialog for toggling it. This
surfaces the existing `allow_platform_charge_fallback` escape hatch (which
routes parent charges to the platform Stripe account when an academy's
connected account isn't charge-ready) so flips are visible and deliberate.
No backend changes — the GET/PUT endpoints and audit logging already existed.

## Deploy notes
none

## Risk / rollback
UI-only read/write of an existing audited endpoint. Rollback = revert PR;
the flag's stored state is unaffected either way.
