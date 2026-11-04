# Academy sport field + badminton curriculum gating

PR: #994

## What changed

- Academies now have a `sport` field, read tenant-scoped through `GetAcademyUseCase`. It is a read-time default, not a migration: an academy document with no `sport` stored (every academy today, including BLNO) reads as `"badminton"`. Nothing is written to existing academy documents.
- `sport` is exposed read-only on `AdminAcademyView` / `GetAcademyOutput`. It is not part of `UpdateAdminAcademyRequest`, so no admin API can set or change it (same platform-set pattern as `invoice_prefix`). Phase 5 editable rules remain out of scope, as instructed.
- `BootstrapAcademyCommand` accepts a `sport`, defaulting to `"badminton"` (today's behaviour for every bootstrap), and writes it onto the new academy document. Not yet exposed on the platform HTTP bootstrap request — only the application command changed.
- `POST /admin/programs/{id}/seed-badminton` now 409s ("Badminton seed is only available for badminton academies") for any academy whose `sport` is not `"badminton"`. The academy is read tenant-scoped off `claims.academy_id`. Badminton academies, and academies with no `sport` stored, are unaffected.
- Admin pathway UI: the "Seed badminton pathway" CTA and BWF-flavoured copy on the pathway list page only show for badminton academies; the create-program name placeholder follows the sport. The pathway detail page defaults new external refs to `BWF_SHUTTLE_TIME` only for badminton programs, and to `ACADEMY_CUSTOM` otherwise.

## BLNO impact

None. BLNO stores no `sport` field, so it continues to read as `"badminton"`, `seed-badminton` continues to succeed for it, and the admin pathway UI shows the same badminton CTA/copy as before. `LessonCard.source`'s domain default and the digest's Shuttle Time citation are unchanged and pinned by a new regression test against BLNO (`acad_blno_badminton`, America/Chicago; local seed `blno`).

## Deploy notes

No migration. `academies.sport` is a read-time default computed in `GetAcademyUseCase`; there is nothing to backfill and no new index. Safe to deploy independently of other batches.

## Risk / rollback

Low risk. The only externally observable behaviour change is the new 409 on `seed-badminton` for a non-badminton academy (a route with no prior sport concept) and admin pathway UI copy differences for non-badminton academies — both no-ops for every academy in production today, since all current academies read as `"badminton"`. Rollback is a plain revert; there is no stored data to undo.
