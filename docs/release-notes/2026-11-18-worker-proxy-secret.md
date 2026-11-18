# worker-proxy-secret

PR: #0

## What changed
Nothing visible yet. The production pipeline now copies the GitHub secret `BFF_PROXY_SHARED_SECRET` into the Cloudflare Worker before every frontend deploy. This prepares for multi-academy mode, where the API trusts the forwarded academy host only when the Worker sends the shared secret. The host preflight script now reads `DB_NAME` when `MONGO_DB_NAME` is unset, so it checks the production database on the API machine.

## Deploy notes
- The Fly secret `V2_PROXY_SHARED_SECRET` is staged with the same value and takes effect on this deploy. Single-academy mode ignores it.
- The frontend deploy now fails early if the GitHub secret `BFF_PROXY_SHARED_SECRET` is missing.

## Risk / rollback
- Risk: low. In single-academy mode every request still belongs to BLNO; the secret only gates the forwarded-host path.
- Rollback: revert the PR. The Worker secret can stay; nothing reads it in single-academy mode.
