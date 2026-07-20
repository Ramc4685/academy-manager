# CI production release automation

PR: #TBD

## What changed

Production CI now publishes one deterministic GitHub Release only after every
changed component deploys successfully and production smoke checks pass. PR
release-note validation is read-only and no longer commits generated stubs or
reruns the full validation matrix when bots edit a PR.

## Deploy notes

No application migration or environment variable is required. The publishing
job uses the repository-scoped `GITHUB_TOKEN` with job-only `contents: write`.
The first successful deployment will aggregate completed release notes since
the existing PR #299 production tag. Replace `PR: #TBD` with this change's PR
number before merge.

## Risk / rollback

The primary risk is a release-publication failure after the application has
already deployed. The workflow remains visibly failed and can be rerun safely:
the publisher refuses to move tags and treats a matching existing tag/release
as success. Revert this CI change to restore the prior deploy-through-smoke
workflow; already-created deployment tags and releases should remain intact.
