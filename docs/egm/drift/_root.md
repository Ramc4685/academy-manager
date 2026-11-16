## README.md

- [wording] README line 173 (`scripts/        Smoke tests, importers, ops utilities`) lists "importers", but `scripts/` (`scripts/smoke`, `scripts/ops`, `scripts/prod`, `scripts/ci`, `scripts/dev`) contains no data importer. It has seed, backfill and audit scripts such as `scripts/dev/seed_badminton_pathway.py:1` and `scripts/dev/backfill_student_pathway_placements.py:1`, plus CI, release and staging tooling. The same gap applies to README line 134 ("data import from your existing spreadsheets and CRM"), which is a sales claim with no importer in the tree.
