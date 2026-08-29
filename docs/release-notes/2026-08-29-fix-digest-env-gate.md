# digest-env-gate

PR: #497

## What changed
`_build_digest_parts` wired the coach daily digest and the admin-triggered
coach digest test with only `email_delivery_enabled` + `resend_api_key`
checked, skipping the `env in {staging, prod}` check the parent digest and
admin compositions both apply. All email send paths now go through the single
env-gated `_build_email_sender` helper. A structural test parses the
composition modules and asserts `ResendEmailSendPort` is constructed only at
approved sites, so a future direct instantiation fails CI. Both docstrings
were corrected: `_build_email_sender` is the single construction site for
adapters that *send*, and the boot-time credential probe is the deliberately
ungated exception that only validates the API key.

## Deploy notes
None. Staging and prod already satisfied the environment check, so delivery
there is unchanged.

## Risk / rollback
Behaviour change for non-prod stacks: a dev or test deployment that was
relying on real coach-digest delivery with `V2_ENV` unset now silently routes
to the stub. No configured deployment is affected (`fly.toml` sets prod,
docker-compose sets dev), but a local stack that wanted real sends must now
set the environment explicitly. That is the intended direction — the bug was
that a dev stack with an inherited prod-shaped env file could email real
coaches from a development database. Roll back by reverting the merge commit;
the structural test would then fail if a direct construction site is
reintroduced, so revert both together.
