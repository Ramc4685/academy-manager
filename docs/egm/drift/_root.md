## README.md

- [wording] README.md:121-123 says production email requires `APP_ENV=production`; `backend/v2/contexts/communications/infrastructure/resend_send_port.py:14` and `backend/v2/shared/config/settings.py:278-283` also enable the real sender when `APP_ENV=staging` (with `email_delivery_enabled=True`).
- [undocumented] README.md:161-174 (Layout) omits top-level items that exist: `Makefile`, `lefthook.yml`, `docker-compose*.yml`, `graphify-out/`, `.github/workflows/` (referenced only in prose at README.md:89).
- [wording] README.md:112 "secure cookies"/"HttpOnly cookies": the code also sets a deliberately non-HttpOnly persona hint cookie (`frontend/lib/auth/persona-hint-cookie.ts:9`). It is a UX hint only, not auth.
