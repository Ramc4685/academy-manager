# Mypy baseline burn-down (audit C1)

The mypy gate was un-broken on 2026-07-20 (audit item C1). At that point the
v2 backend had **559 pre-existing strict-mode errors in 171 files** (517 files
checked). They are frozen in `backend/mypy-baseline.txt` via
[mypy-baseline](https://pypi.org/project/mypy-baseline/); CI blocks **new**
errors only.

## Commands (run from the repo root)

```bash
# What CI runs — fails on any error not in the baseline:
mypy --config-file backend/pyproject.toml -p backend.v2 \
  | mypy-baseline filter --baseline-path backend/mypy-baseline.txt

# After fixing pre-existing errors, shrink the baseline (commit the result):
mypy --config-file backend/pyproject.toml -p backend.v2 \
  | mypy-baseline sync --baseline-path backend/mypy-baseline.txt
```

Rules:

- Never run `sync` to absorb NEW errors — fix them instead. `sync` is only for
  shrinking the baseline after fixing old ones (the diff must only delete lines).
- Do not re-add `# type: ignore` comments to dodge the gate.

## Baseline composition at freeze (2026-07-20)

| Error code | Count | Wave |
|---|---|---|
| `unused-ignore` | 376 | ✅ fixed in the C1 PR (stale ignores deleted) |
| `no-untyped-def` | 104 | 1 — mechanical (add signatures) |
| `type-arg` | 95 | 3 |
| `arg-type` | 85 | 2 |
| `no-any-return` | 65 | 2 |
| `attr-defined` | 55 | 2 |
| `call-overload` | 54 | 2 |
| `union-attr` | 48 | 2 |
| `operator` | 17 | 3 |
| `assignment` | 16 | 2 |
| `no-untyped-call` | 4 | 1 — mechanical |
| `no-redef` | 4 | 1 — mechanical |
| `misc` | 3 | 3 |
| `var-annotated` | 2 | 1 |
| `return-value` | 2 | 2 |
| `index` | 2 | 2 |
| `call-arg` | 2 | 2 |
| `comparison-overlap` | 1 | 3 |
| **Total remaining** | **559** | |

Suggested burn-down (one wave per PR, per the C1 plan): wave 1 first
(`no-untyped-def`/`no-untyped-call` — mechanical), then wave 2
(`arg-type`/`assignment`/`union-attr`/... — real signature and narrowing fixes),
leaving `type-arg`/`misc`/`operator` last. Update this table as waves land.

## Notes

- The original abort ("Source file found twice under different module names")
  was caused by two package bases: `mypy_path = ".."` plus running from
  `backend/` with `files = ["v2"]`. Fix = single base: run from the repo root
  with `-p backend.v2`; `files`/`mypy_path` were removed from
  `backend/pyproject.toml`. Deleting `backend/__init__.py` alone does NOT fix
  it — with `explicit_package_bases = true`, `__init__.py` is irrelevant to
  module-name computation (the plan's Alternative B was the fix that worked).
- `opentelemetry.*`, `openpyxl.*`, `requests.*`, `apscheduler.*` were added to
  the `ignore_missing_imports` override list (untyped or not installed in the
  checking env), matching the existing pattern for `motor.*`/`stripe.*`/etc.
- `disable_error_code` was evaluated and rejected as the freeze mechanism: it
  makes the ~167 load-bearing `# type: ignore[<code>]` comments for disabled
  codes report as `unused-ignore`, forcing removal of suppressions that must
  survive until their wave is fixed.
