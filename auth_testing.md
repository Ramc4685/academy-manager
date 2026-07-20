# Auth Testing Playbook — Badminton Academy Manager

## Setup
- Backend: FastAPI on `:8001` (supervisor), MongoDB local.
- Firebase Auth is the primary login path when `FIREBASE_AUTH_ENABLED=true`.
- Local JWT cookies are kept only as a fallback when Firebase auth is disabled.
- Admin seeded from `.env` on startup via `ADMIN_EMAIL`.
- Demo coach and parent accounts are disabled by default.

## MongoDB Indexes (created at startup)
- `users.email` unique
- `invites.token` unique
- `password_reset_tokens.expires_at` TTL
- `login_attempts.identifier`
- `enrollments.{session_id,student_id}` unique
- `attendance.{session_id,student_id,date}` unique
- `payments.{enrollment_id,period}` unique

## API Tests

### 1. Firebase login and call /me

The frontend signs in with Firebase and sends:

```
Authorization: Bearer <firebase_id_token>
```

Then:

```
curl -H "Authorization: Bearer <firebase_id_token>" http://localhost:8001/api/auth/me
```

Expected: returns the matching local user with `role`.

### 2. Local fallback login when Firebase is disabled
```
curl -c /tmp/cookies.txt -X POST http://localhost:8001/api/auth/login \
  -H "Content-Type: application/json" \
  -d '{"email":"admin@example.com","password":"$ADMIN_PASSWORD"}'
curl -b /tmp/cookies.txt http://localhost:8001/api/auth/me
```
Expected: returns user with `role:"admin"`.

### 3. Register parent
```
curl -c /tmp/parent.txt -X POST http://localhost:8001/api/auth/register \
  -H "Content-Type: application/json" \
  -d '{"email":"newparent@x.com","password":"Test@12345","name":"Test Parent"}'
```
Expected: user object with `role:"parent"`.

### 3. Admin invites coach
```
curl -b /tmp/cookies.txt -X POST http://localhost:8001/api/invites \
  -H "Content-Type: application/json" \
  -d '{"email":"newcoach@x.com","role":"coach"}'
```
Expected: returns invite with token URL.

### 4. Brute force
5 wrong passwords for same email → 6th attempt returns 429.

### 5. Logout clears cookies
```
curl -b /tmp/cookies.txt -X POST http://localhost:8001/api/auth/logout
```
Expected: 200 and Set-Cookie clears tokens.

## Role-based access checks
- Coach calling `/api/payments` → 403
- Parent calling `/api/expenses` → 403
- Anonymous calling `/api/dashboard/admin` → 401
