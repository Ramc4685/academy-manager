# Test Result Index

This file is intentionally small to avoid merge conflicts.
Use the per-task ledgers under `docs/test-results/active/` for current handoffs.

## Active Test Result Files

- [2026-06-01-production-defect-bundle](docs/test-results/active/2026-06-01-production-defect-bundle.md)
- [2026-06-03-pause-resume-autopay](docs/test-results/active/2026-06-03-pause-resume-autopay.md)
- [2026-06-04-student-profile-redesign-options](docs/test-results/active/2026-06-04-student-profile-redesign-options.md)
- [2026-06-05-skill-pathway-progress-overview](docs/test-results/active/2026-06-05-skill-pathway-progress-overview.md)
- [2026-06-06-blno-feature-user-testing](docs/test-results/active/2026-06-06-blno-feature-user-testing.md)
- [2026-06-07-parent-portal-attractive-home](docs/test-results/active/2026-06-07-parent-portal-attractive-home.md)
- [2026-06-08-backend-deployment-failed-action-27169842973](docs/test-results/active/2026-06-08-backend-deployment-failed-action-27169842973.md)
- [2026-06-08-blno-production-login-failure](docs/test-results/active/2026-06-08-blno-production-login-failure.md)
- [2026-06-08-marvy-labs-ip-protection-and-production-branding-plan](docs/test-results/active/2026-06-08-marvy-labs-ip-protection-and-production-branding-plan.md)
- [2026-06-09-coach-payroll-percentage-rules](docs/test-results/active/2026-06-09-coach-payroll-percentage-rules.md)
- [2026-06-09-prod-stripe-billing-portal-failure](docs/test-results/active/2026-06-09-prod-stripe-billing-portal-failure.md)
- [2026-06-09-session-skill-board](docs/test-results/active/2026-06-09-session-skill-board.md)
- [2026-06-10-coach-parent-role-resolution](docs/test-results/active/2026-06-10-coach-parent-role-resolution.md)
- [2026-06-11-billing-invoice-ledger-requirements](docs/test-results/active/2026-06-11-billing-invoice-ledger-requirements.md)
- [2026-06-11-coach-daily-lesson-guidance](docs/test-results/active/2026-06-11-coach-daily-lesson-guidance.md)
- [2026-06-12-stripe-payment-hotfix](docs/test-results/active/2026-06-12-stripe-payment-hotfix.md)
- [2026-06-13-admin-pause-digest-followups](docs/test-results/active/2026-06-13-admin-pause-digest-followups.md)
- [2026-06-13-admin-teaching-plan-visibility](docs/test-results/active/2026-06-13-admin-teaching-plan-visibility.md)
- [2026-06-13-parent-skill-updates](docs/test-results/active/2026-06-13-parent-skill-updates.md)
- [2026-06-14-prod-coach-pay-rate-500-hotfix](docs/test-results/active/2026-06-14-prod-coach-pay-rate-500-hotfix.md)
- [2026-06-15-billing-ledger-workflow-completion](docs/test-results/active/2026-06-15-billing-ledger-workflow-completion.md)
- [2026-06-15-onboarding-waiver-registration-fix](docs/test-results/active/2026-06-15-onboarding-waiver-registration-fix.md)
- [2026-06-16-production-launch-hardening](docs/test-results/active/2026-06-16-production-launch-hardening.md)
- [2026-06-16-release-candidate-validation-blno-staging](docs/test-results/active/2026-06-16-release-candidate-validation-blno-staging.md)

## Required Workflow

- Start a task: `scripts/dev/test_result.py start "task title" --problem "..."`
- Add status: `scripts/dev/test_result.py log <slug> --agent main --status working --message "..."`
- Add verification: `scripts/dev/test_result.py verify <slug> --message "..."`
- Close a task: `scripts/dev/test_result.py close <slug>`
- Do not manually edit large shared status blocks in this file.

## Learning Loop

- Keep task-specific evidence in the relevant active ledger.
- Promote reusable lessons to `docs/agent/testing-verification.md` or `docs/agent/feedback-loop.md`.
- Archive completed task ledgers with the `close` command.
