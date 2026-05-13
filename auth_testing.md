# Auth Testing Playbook — Badminton Academy Manager

## Setup
- Backend: FastAPI on `:8001` (supervisor), MongoDB local.
- JWT cookie names: `access_token` (15 min), `refresh_token` (7 days). httpOnly, samesite=lax.
- Admin seeded from `.env` on startup: `admin@badminton.app` / `Admin@12345`.
- Demo coach: `coach@badminton.app` / `Coach@12345`
- Demo parent: `parent@badminton.app` / `Parent@12345`

## MongoDB Indexes (created at startup)
- `users.email` unique
- `invites.token` unique
- `password_reset_tokens.expires_at` TTL
- `login_attempts.identifier`
- `enrollments.{session_id,student_id}` unique
- `attendance.{session_id,student_id,date}` unique
- `payments.{enrollment_id,period}` unique

## API Tests

### 1. Login admin and call /me
```
curl -c /tmp/cookies.txt -X POST http://localhost:8001/api/auth/login \
  -H "Content-Type: application/json" \
  -d '{"email":"admin@badminton.app","password":"Admin@12345"}'
curl -b /tmp/cookies.txt http://localhost:8001/api/auth/me
```
Expected: returns user with `role:"admin"`.

### 2. Register parent
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
