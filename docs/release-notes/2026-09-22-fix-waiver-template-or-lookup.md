# fix-waiver-template-or-lookup

PR: #TBD

## What changed

- The last "match either of two fields" lookup left over from #878 (#894 step 3). The waiver-template repositories looked a template up as `waiver_template_id = X or _id = X`, one query, whenever the id happened to be valid ObjectId hex. Production's MongoDB 8.0 scans the academy's templates for that shape instead of using the per-academy id index (the same behaviour #886 fixed for payments and invoices). The admin template reads, publish and assign-to-registration, and the parent waiver-signing path all went through it.
- They now look the template up by `waiver_template_id` first, and only if that misses and the id is valid ObjectId hex, by `_id`. Publish and assign update the document they resolved, by `_id`. Same documents in the same preference order; each read is index-served.

## Deploy notes

None. No migrations, no env vars.

## Risk / rollback

Low. `waiver_templates` holds a handful of documents per academy, so this is about correctness of the pattern rather than measurable latency. Existing waiver tests pass unchanged. To roll back, revert this PR's merge commit.
