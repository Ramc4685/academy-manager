# Logo upload (Settings overhaul Phase 4 PR 13b)

PR: #TBD

## What changed

- **Academy profile > Brand** now has an upload control: choose a file or drag one onto it (PNG or JPG, up to 2 MB, checked in the browser first with plain error copy). The preview updates at once; the new logo is saved with the tab's normal Save button. Pasting a link still works ("Or paste a logo link"), and now must start with `https://`.
- **New endpoint `POST /api/v2/admin/academy/media`** (admin role, tenant-scoped, one multipart `file` field). It refuses a body over 2 MB before parsing it, decides the format from the file's real bytes (PNG or JPEG only, never the filename or Content-Type), rejects images over 4096 x 4096 pixels, re-encodes the image (EXIF orientation applied, then every EXIF/ICC/text chunk dropped), downsizes to at most 512 px on the longest side and always stores a PNG (the Outlook-safe copy). Bad files answer 422 with a plain message, oversize 413, more than 20 uploads an hour per academy 429, storage outage 502. When no bucket is configured it answers 503 ("Logo upload is not set up yet. Paste a link to your logo instead.") and the link field keeps working.
- **Storage:** Firebase Storage through the Admin SDK, object path `academies/<academy_id>/logo/<uuid>.png` (academy from the signed-in tenant, never the request). Objects are never overwritten or deleted, so older emails keep their old logo. Public read is by a Firebase download-token URL (`https://firebasestorage.googleapis.com/v0/b/<bucket>/o/<path>?alt=media&token=<uuid>`); the bucket itself is not public.
- **One writer for `logo_url`:** the endpoint only returns `{logo_url}`; `PATCH /admin/academy` saves it. That PATCH now rejects a non-`https` logo link with 422 (emails and the parent app already ignored non-https logos).
- **Audit:** each upload writes an `academy_media` row (academy, object path, URL, uploader, size, sha256, dimensions, time). It is tenant-owned, so the tenant data export picks it up automatically; the stored image objects themselves are not part of that export (see follow-ups).
- **Readers checked:** the email header (`<img src>` is HTML-escaped, covered by a test with a real token URL), the admin/parent/coach app mark and public page (`safeHttpsUrl` keeps the query string) and the parent dashboard `<img>` all take an https URL, so the Firebase URL works everywhere with no CSP change: `img-src` already allows `https://firebasestorage.googleapis.com` and was not touched.
- `apiFetch` no longer forces `Content-Type: application/json` on a `FormData` body (the browser must set the multipart boundary).

## Deploy notes

No migration. BLNO behaviour is unchanged until the bucket is configured and someone uploads.

Owner steps before the upload button works in production:

1. **Enable Firebase Storage** on the Firebase project `academy-courtmastr` (Console > Build > Storage > Get started).
2. **Bucket name:** set the Fly secret `V2_MEDIA_STORAGE_BUCKET` to the bucket shown in the Storage console. It is deliberately not guessed: projects created before Oct 2024 use `academy-courtmastr.appspot.com`, newer ones `academy-courtmastr.firebasestorage.app`.
3. **Storage rules:** deny all client reads and writes. The Admin SDK bypasses rules and token URLs still work.
   ```
   rules_version = '2';
   service firebase.storage {
     match /b/{bucket}/o {
       match /{allPaths=**} { allow read, write: if false; }
     }
   }
   ```
4. **Service-account permission:** the service account the backend uses (`FIREBASE_CREDENTIALS_JSON` / `FIREBASE_CREDENTIALS_FILE`) needs **Storage Object Admin** on that bucket (`roles/storage.objectAdmin`; creating objects and setting their metadata are needed, deleting is not).
5. Then upload a logo in Settings > Academy profile and check it in a test email and the parent app.

Until steps 1 to 4 are done the endpoint answers 503 and Settings shows that message under the upload control.

## Risk / rollback

- New attack surface is an authenticated file upload. Mitigations: admin-only, body cap before parse, Pillow-decided format restricted to PNG/JPEG, pixel cap checked from the header, full re-encode from raw pixels (no metadata or trailing bytes survive), fresh uuid path per academy, per-academy hourly cap. Files are served from `firebasestorage.googleapis.com`, never from our origin.
- Objects are immutable and never deleted, so storage grows by at most a few tens of KB per upload; there is no cleanup job.
- Rollback: revert this PR. Stored objects and `academy_media` rows stay (harmless); logos already saved into `academies.logo_url` keep working because they are plain https URLs.
