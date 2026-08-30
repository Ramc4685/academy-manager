# login-failure-reason

PR: #453

## What changed
Auth 401s now carry the reason the backend rejected the sign-in (missing
membership, unknown user, inactive account, invalid/unverified token,
unresolvable tenant) instead of collapsing into a bare 401. `/post-login` and
the persona guards forward that reason to `/login?error=<code>`, where the
login page renders a parent-friendly explanation — so a rejected login shows
"Your account isn't set up for this academy yet" rather than a blank form.
Only the machine-readable code crosses the boundary; the underlying exception
message (which can embed user ids) is never sent to the client.

## Deploy notes
None. No migrations, no new env vars.

## Risk / rollback
Low. The 401 status is unchanged — only the response body gained
`error.details.reason`, and the login page gained a message. Revert the PR to
restore the silent bounce.
