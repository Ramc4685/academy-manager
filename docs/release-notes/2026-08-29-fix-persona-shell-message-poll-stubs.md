# persona-shell-message-poll-stubs

PR: #498

## What changed
Both persona shells poll an inbox on every page (UIM13) — the parent layout
`/api/v2/parent/messages`, the coach layout `/api/v2/coach/messages` — and no
spec stubbed either. With no catch-all in `mock-api.ts` the requests proxied
to a dead backend origin, returned 500, and tripped the clean-console
assertion in specs unrelated to messaging. Adds `stubParentMessages` and
`stubCoachMessages` and wires them into the parent specs, the coach specs,
and the launch route matrix's two shell helpers, all defaulting to an empty
inbox. Also gives the franchise-rollup spec a 20s first-navigation timeout:
it is the only spec that visits `/owner`, so it always pays that route's cold
dev-server compile inside its own assertion budget.

## Deploy notes
None. Test-only; no application code changes.

## Risk / rollback
Low. The stubs return an empty inbox, so any future spec asserting on real
message content must override them rather than rely on the default — the
helpers take an optional messages array for that. Revert the commits if a
spec needs the unstubbed behaviour, though that would restore the 500s. The
underlying gap remains that unmatched `/api/v2/**` requests fall through to a
dead origin instead of failing loudly; a catch-all stub is tracked separately
in the audit backlog.
