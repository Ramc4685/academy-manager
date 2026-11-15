## README.md

- [undocumented] README.md:83-84 says the `academy-next` Worker owns `academy.courtmastr.com/*`. `frontend/wrangler.jsonc:18-25` also routes `*.courtmastr.com/*` (zone `courtmastr.com`) to the Worker. The wildcard tenant route is not mentioned.
