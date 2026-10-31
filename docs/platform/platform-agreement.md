# Platform agreement (DRAFT, owner to supply)

> **DRAFT. This file is a placeholder, not an agreement.** The agreement text
> is an owner/legal input. No legal wording has been written here on purpose.
> The owner (with legal advice) supplies the text and a version string before
> any academy is asked to accept it.

## What the product stores (roadmap L9c)

The tenant record in `academies` carries:

| Field | Meaning |
| --- | --- |
| `fee_model` | How the platform charges the academy. Only `flat_monthly` exists (owner decision 2026-09-22). |
| `platform_agreement_version` | The version string of the agreement the academy accepted. |
| `platform_agreement_accepted_at` | When the acceptance was recorded (UTC, stamped by the server). |
| `platform_agreement_accepted_by` | The academy-side signatory, for example the owner's email. |

A platform admin records an acceptance on the platform tenant page
(`POST /api/v2/platform/tenants/{academy_id}/agreement`). A tenant in
`provisioning` cannot be activated until an acceptance is on record
(409 `Platform.TenantAgreementNotAccepted`). Every recording is in the platform
audit trail (`tenant.agreement_accepted`, with before/after snapshots).

Migration `0200_tenant_fee_model_and_agreement` sets `fee_model` to
`flat_monthly` on existing academies and leaves the agreement fields null.
It does not invent an acceptance for the academy that is already live.

## Owner inputs still needed

- [ ] Agreement text (legal review).
- [ ] Version string for the first published text (for example `2026-10`).
- [ ] Where the academy reads and accepts it (link sent by email, signed PDF,
      or an in-app page), and who at the academy signs.
- [ ] Whether the already-live academy should accept retroactively; if so,
      record it on the platform tenant page once it has really been given.

## Agreement text

_Owner to supply. Intentionally empty._
