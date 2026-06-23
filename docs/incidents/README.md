# Incident Response Notes

Use this directory for production incident notes and rollback records.

## Launch Incident Checklist

1. Name an incident lead.
2. Record start time, affected surface, and severity.
3. Check backend health:

   ```bash
   fly status -a courtmastr-academy-api
   fly checks list -a courtmastr-academy-api
   curl -fsS https://api.academy.courtmastr.com/api/v2/healthz
   ```

4. Check frontend health:

   ```bash
   curl -I https://academy.courtmastr.com
   cd frontend && npx wrangler deployments list --name academy-next
   ```

5. Check recent backend logs:

   ```bash
   fly logs -a courtmastr-academy-api --no-tail
   ```

6. Decide: fix forward, disable feature path, or rollback.
7. Before rollback, capture current release/deployment ids.
8. After mitigation, verify admin, parent, and coach critical paths.
9. Record the final status, root cause, and follow-up actions.

## Note Template

```text
# Incident - YYYY-MM-DD - short-title

Severity:
Lead:
Start:
End:

Affected users:
Affected systems:

Detection:
Impact:
Root cause:

Actions taken:
- 

Verification:
- 

Follow-up:
- 
```

