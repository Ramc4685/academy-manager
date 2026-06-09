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

If `/me` returns `401`, open the Postman Console and confirm the outgoing
request includes `Authorization: Bearer eyJ...`. The response `Headers` tab
only shows headers returned by the server; it will not show the request's
Authorization header.

The collection defaults to:

- `baseUrl`: `https://api.academy.courtmastr.com`
- `apiPrefix`: `/api/v2`
- `academyId`: `blno`
- `tenantHost`: `blno-academy.courtmastr.com`

The collection sends `academyId` as both `X-Internal-Academy-Id` and
`X-Academy-Id` so direct Postman calls to the API can resolve the BLNO tenant
instead of relying on the browser host.
It also sends `tenantHost` as `X-Forwarded-Host`, matching the production
tenant host used by the browser app.

Do not store real tokens in the repo. Keep `firebaseIdToken` only in your local Postman workspace.

Write requests in `02 - Write Curriculum - Use Carefully` and `03 - Student Progress and Placement` mutate production data. Update one record at a time, then verify with `Get Full Pathway`, `Get Pathway Progress Overview`, or the app UI.

## Creating the Local Seed Pathway in Prod

The folder `04 - Create Local Pathway Template - Empty Program Only` was
generated from the local badminton seed template in
`backend/v2/contexts/curriculum/application/use_cases/seed_curriculum.py`.

Use it only when the selected `programId` is an empty program. These requests
are create-only and not idempotent. Running them against a program that already
has levels or skills will create duplicates.

Recommended run order:

1. Run `00 - Auth and Smoke / Me - Verify Admin Token`.
2. Run `01 - Read Current Pathway / List Programs`.
3. If needed, create a new empty program with
   `02 - Write Curriculum - Use Carefully / Create Program`.
4. Run `04 - Create Local Pathway Template - Empty Program Only /
   00 - Verify Selected Program Is Empty`.
5. In the Postman Collection Runner, run the whole
   `04 - Create Local Pathway Template - Empty Program Only` folder in order.
6. Run `99 - Verify Full Pathway After Create`.

The generated template creates:

- 6 levels
- 33 skills
- 99 criteria
- 6 metadata-only external references
