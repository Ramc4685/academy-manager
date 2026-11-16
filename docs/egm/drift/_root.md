## README.md

- [wording] README lines 83-84 ("`academy-next` Cloudflare Worker owns `academy.courtmastr.com/*` directly through a Worker Route") list one route. `frontend/wrangler.jsonc:18-26` declares two routes, the second being the wildcard `*.courtmastr.com/*`, which the README does not mention.
- [wording] README lines 121-123 ("production email requires `APP_ENV=production`, a verified Resend sender, and an explicit enable flag"). `backend/v2/contexts/communications/infrastructure/resend_send_port.py:14` also enables the real sender when `APP_ENV=staging`. The flag is named `EMAIL_DELIVERY_ENABLED` (`stub_send_port.py:6`) and the README does not name it.
