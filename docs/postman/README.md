# Postman Collections

## Skill Pathway Production Admin

Import `academy-manager-skill-pathway-prod.postman_collection.json` into Postman.

Before calling protected requests:

1. Sign in to the production app as an admin.
2. Get a fresh Firebase ID token for that admin session. The simplest path is
   Chrome DevTools -> Network -> click any `/api/v2/...` request -> copy the
   `Authorization` request header value, then paste only the token after
   `Bearer `.
3. Paste it into the `firebaseIdToken` variable. Use either the collection
   variable or your selected Postman environment variable. The value should
   start with `eyJ`, not `Bearer eyJ`.
4. Run `00 - Auth and Smoke / Me - Verify Admin Token`.
5. Run read requests before write requests.

The collection defaults to:

- `baseUrl`: `https://api.academy.courtmastr.com`
- `apiPrefix`: `/api/v2`
- `academyId`: `blno`

Do not store real tokens in the repo. Keep `firebaseIdToken` only in your local Postman workspace.

Write requests in `02 - Write Curriculum - Use Carefully` and `03 - Student Progress and Placement` mutate production data. Update one record at a time, then verify with `Get Full Pathway`, `Get Pathway Progress Overview`, or the app UI.
