# Admin↔Coach Toggle & Non-Google Parent Login — Design

**Date:** 2026-07-09
**Status:** Approved
**Scope:** Two independent production enhancements. Each can ship as its own slice/PR.

---

## Enhancement 1: Admin ↔ Coach view toggle

### Problem

Some admins also coach. They need to mark attendance and use the coach screens for
their own sessions, without a second account. Today the admin role-management path
replaces a user's roles wholesale, and the UI has no way to switch personas.

### Decision

Real dual roles + a persona switcher. No impersonation. The admin holds both
`admin` and `coach` roles on their academy membership; the existing coach screens
work unchanged and show only sessions where that user is the assigned coach.

### Backend

- `academy_memberships.roles` already supports multiple roles; `require_persona("coach")`
  already authorizes by `"coach" in claims.roles`; coach attendance/today routes already
  scope by `claims.user_id` against the occurrence's assigned-coach fields. **No coach-route changes.**
- Fix the destructive role update: `MongoUserRepo.change_role`
  (`backend/v2/contexts/identity/infrastructure/mongo_user_repo.py:461`) does
  `$set {"role": role, "roles": [role]}`. Replace/augment with additive semantics:
  an admin endpoint to add or remove a role on a user's membership (and mirror to the
  legacy `users.roles` field), never silently dropping other roles.
- Expose on the admin users interface: `POST /admin/users/{id}/roles` (add) and
  `DELETE /admin/users/{id}/roles/{role}` (remove), or an equivalent roles-list update
  on the existing user-update endpoint — follow existing directory_routes conventions.
- Guardrail: an admin may not remove their own `admin` role (avoid lock-out).

### Admin setup flow

- From the admin Users screen, grant the coach role to any user (including self).
- Once a user has the coach role they appear in the coach picker for session
  assignment like any other coach (verify the coach list query keys off the coach role).

### Frontend

- Persona switcher shown only when the current user's roles include both `admin` and `coach`
  (from `/me`):
  - Admin layout header (near the academy/tenant switcher): "Coach view" → `/coach/today`.
  - Coach layout: "Admin view" → `/admin`.
- Post-login landing unchanged (`homeForRoles`: admin → `/admin`).
- Users with a single role never see the switcher.

### Rejected alternative

"View as any coach" impersonation: more powerful, but adds audit/attribution complexity
and is not what's needed — the admin is a real coach for their own sessions.

---

## Enhancement 2: Non-Google parent login (admin-created account + set-password email)

### Problem

Some parents use Yahoo/Hotmail etc. and won't use Google sign-in. Their kids are
already registered; the parents only need to log in and pay. Email/password login
already exists in the app — the gap is account creation and credential delivery.

### Decision

Admin creates the parent account (email is already on file); the system sends a
branded **"Set your password"** email using a Firebase password-reset link. This is
the standard invite pattern and safer than a one-time password: nothing secret sits
in the inbox, the link expires, and the parent chooses their own password.
Completing the reset link also marks the Firebase email verified, which satisfies
`_require_verified_password_provider_email` in `load_auth_claims.py`.

### Backend

- Reuse the existing provisioning path (`create_admin_user` /
  `POST /admin/users` and `POST /admin/users/bulk-invite` in
  `backend/v2/interfaces/admin/directory_routes.py`): Firebase user + user doc +
  active `parent` membership.
- Add the missing delivery step: after provisioning, generate a password-reset link
  via the Firebase Admin SDK (`generate_password_reset_link`) and send it through
  Resend with academy branding: "Your {academy} account is ready — set your password
  to view your children and make payments."
- Record invite state on the user/membership (e.g. `invite_sent_at`) to power the
  re-send UI. Auto-send on creation; explicit re-send endpoint.

### Linking kids

- Students attach to a parent via `Student.parent_id`.
- If existing students already carry this parent's email/family reference, attach them
  to the new account during creation; otherwise the admin selects which students belong
  to the parent as part of the create flow.
- Implementation must verify how the current production students are attached and
  ensure no orphaned students (student without a resolvable parent login) remain
  for invited families.

### Admin UI

- On the parent row/detail in the admin directory: "Send login invite" button,
  re-send option, and an "Invite sent {date}" indicator.

### Parent experience

Open email → set password (Firebase hosted or in-app reset page) → log in at the
normal login page with email + password → land on `/parent/payments`.

---

## Testing

- **Backend unit:** additive role add/remove (no clobbering, self-lockout guard);
  invite email generation and invite-state recording.
- **Backend interface:** admin role endpoints; invite/re-send endpoints; coach routes
  accessible for a dual-role user.
- **End-to-end (staging):** (1) grant self coach role, toggle to coach view, mark
  attendance on an assigned session; (2) create a parent with a non-Google email,
  receive set-password email, set password, log in, reach payments with kids visible.

## Out of scope

- Coach→admin impersonation / "view as" other coaches.
- Parent self-registration auto-linking to existing students (may come later as a fallback).
- Changes to Google sign-in or the public register flow.
