# Firebase Auth Emulator config

Used by `docker-compose.saas.yml` to run a local Firebase Auth emulator for
SaaS staging. Auth-only — Firestore/Functions/Storage emulators are NOT
enabled because the app does not use them in SaaS mode (Mongo is the SaaS
data store).

- `firebase.json` — emulator ports + UI
- `.firebaserc` — pinned to project id `academy-courtmastr` to match the
  frontend Firebase web config baked into the docker-compose frontend build.

Do not point this at a real Firebase project. The emulator accepts any API
key and uses unsigned dev tokens.
