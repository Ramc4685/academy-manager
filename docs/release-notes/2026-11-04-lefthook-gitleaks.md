# lefthook-gitleaks

PR: #1114

## What changed
Adds an opt-in pre-commit hook (`lefthook.yml`) that runs on staged files only: a gitleaks secret scan, `ruff check --fix` and `ruff format` on backend Python (pinned to the CI ruff version), and `eslint --fix` on frontend TS/TSX. `.gitleaks.toml` extends the default rules with one that catches Google API keys followed by `:`, `&`, `,` or `)`, which the built-in rule misses in URLs and logs. `.gitleaksignore` baselines 13 reviewed history findings (test fixtures).

## Deploy notes
Developer tooling only: no app code, no migration, nothing to deploy. Each clone opts in with `brew install lefthook gitleaks && lefthook install`.

## Risk / rollback
No runtime risk. A staged edit to a file with a known false positive (for example `mobile/ios/App/App/GoogleService-Info.plist`) will fail the hook until it is added to `.gitleaksignore`. Skip once with `git commit --no-verify`, or run `lefthook uninstall` to turn it off. Revert this PR to remove it entirely.
