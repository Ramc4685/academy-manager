# Lifecycle completeness matrix and derivation spec

## What changed

- Adds `docs/reviews/2026-09-12-lifecycle-completeness.md`: a 38-row orphan matrix (what happens to every dependent record when its parent entity ends), 32 gaps not covered by the batch-3b/3c plan, and the ordered derivation rules for the person lifecycle that #773 implements. Findings were filed as #782 to #788 and as comments on #772 to #778. Docs only.

## Deploy notes

- None. No code, migration or environment change.

## Risk / rollback

- None: a docs file. Rollback is a revert.

PR: #789
