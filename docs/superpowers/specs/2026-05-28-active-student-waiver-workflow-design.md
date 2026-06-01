# Active Student Waiver Workflow Design

## Feature Summary

The academy uses one required liability waiver at a time. When an admin marks an active waiver as required, it applies automatically to every active student in the academy. Admins need to see which students are signed, pending, or outdated, send reminders to unsigned families, and let parents digitally accept the current waiver for their active children.

## Primary User Action

Admins should be able to make the current active waiver required, then drive the unsigned list to zero from the Waivers and Students screens.

## Design Direction

This is an operational compliance workflow, so the UI should be direct and status-heavy. The important signal is not the waiver text itself; it is whether each active student is cleared to participate. Keep the existing admin table style and use compact status chips rather than a new visual language.

## Layout Strategy

The Waivers page remains the command center: current waiver summary, template management, and per-student status. The Students list gains a Waiver column so an admin scanning the roster can immediately see `SIGNED`, `NEEDED`, or `OUTDATED`. Student detail gets the same status near the top with the signed version/date when available.

The parent side gets a dedicated `/parent/waivers` screen. It shows the current required waiver text, each active child affected, and one digital acceptance button. Acceptance records one signature row per active child that still needs the current waiver.

## Key States

- No required waiver: admin sees `Not required`; parent waiver page says no waiver is required.
- Required waiver, no signature: student status is `NEEDED`.
- Required waiver, older signature: student status is `OUTDATED`.
- Required waiver, current signature: student status is `SIGNED`.
- Reminder sent: admin gets count of parent reminders recorded/sent.
- Parent accept success: parent sees all active children marked signed.
- Missing parent email or no active children: skip reminder/acceptance for that row and report skipped count.

## Interaction Model

`Require` on an active template means "require this waiver for all active students." It does not create per-student assignment rows; requirement is derived from the single active registration-required template.

`Send reminders` targets students whose waiver status is `NEEDED` or `OUTDATED`, groups by parent, and records one reminder per parent with a link to `/parent/waivers`. In local/test environments it must not send real email.

Parents open `/parent/waivers`, review the text, enter/confirm signer name implicitly from their account when available, and click accept. The backend writes immutable `waiver_signatures` rows with template id, content hash, signer, timestamp, IP, and user agent.

## Content Requirements

- Admin button: `Send reminders`
- Admin success: `Reminder sent to N parent(s).`
- Student status labels: `SIGNED`, `NEEDED`, `OUTDATED`, `NOT REQUIRED`
- Parent CTA: `Accept waiver`
- Parent success: `Waiver accepted for your active child(ren).`

## Architecture

Use v2 onboarding boundaries. Admin BFF routes stay under `backend/v2/interfaces/admin/waiver_routes.py`; parent routes get a focused waiver route under `backend/v2/interfaces/parent/`. Waiver status is derived from `waiver_templates` and `waiver_signatures`, with legacy `waiver_acceptances` still read for display compatibility. New parent acceptance writes only the per-student `waiver_signatures` model.

## Testing

Backend tests cover admin reminder target filtering, parent waiver read, parent acceptance writing one signature per active child, and student list waiver status. Frontend tests cover Waivers reminder action, Students waiver column, and parent acceptance screen. Manual local verification uses `http://blno.localhost:3001`.
