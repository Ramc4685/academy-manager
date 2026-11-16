## README.md

- [wording] (previous report) README line 173 (`scripts/        Smoke tests, importers, ops utilities`) lists "importers", but `scripts/` has no data importer. It holds smoke, CI, ops, prod-repair, seed, backfill and audit scripts, for example `scripts/dev/seed_badminton_pathway.py:1` and `scripts/dev/backfill_student_pathway_placements.py:1`. The sales claim at README line 134 ("data import from your existing spreadsheets and CRM") likewise has no importer in the tree.
- [wording] (NEW) README line 51 ("runs as a managed, multi-region cloud service") does not match `backend/fly.toml:2` (`primary_region = "ord"`, single region) and `backend/fly.toml:54` (`min_machines_running = 1`). The README's own diagram (line 63) and stack table (line 76) say region `ord` only.
