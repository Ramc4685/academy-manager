# Data Retention Policy Draft

Status: draft, policy-first gate for admin deletion controls.

## Scope

This policy covers academy data stored by the v2 BFF/DDD surfaces, including users, students, enrollments, attendance, billing records, messages, audit logs, waiver acceptances, and settings.

## Current Product Rule

Admin Settings may expose export controls, but must not expose deletion, anonymization, or destructive retention controls until this policy is approved and translated into backend workflows.

## Retention Defaults

- Billing and payout records are retained for accounting and dispute support.
- Audit logs are retained for operational accountability and security review.
- Waiver acceptances are retained while a student is active and for a later legal retention period to be approved.
- Attendance and progress records are retained while the student account is active.
- Messages are retained until a product/legal deletion window is approved.

## Deletion Workflow Requirements

Before any admin Data panel deletion control ships, the implementation plan must define:

- Which records are hard-deleted, anonymized, or tombstoned.
- Which billing, payout, audit, and waiver records must survive deletion.
- Who can request deletion and who can approve it.
- How deletion requests are audited.
- How Stripe, Firebase Auth, email, and object storage records are reconciled.
- How parent/student identity references are handled across historical records.

## Open Decisions

- Legal retention window for waiver acceptances.
- Accounting retention window for payments, discounts, refunds, expenses, and payouts.
- Whether student learning history is anonymized or fully deleted.
- Whether message deletion is per-user, per-thread, or academy-wide.
- Whether deletion requests need a cooling-off period.
