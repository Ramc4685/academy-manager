# Drop duplicate InvoiceLineDto field declarations

PR: #796

## What changed
- `InvoiceLineDto` in `backend/v2/interfaces/admin/views.py` declared `line_type`, `quantity`, and `unit_amount_cents` twice. The redundant second set is removed; field order and defaults are unchanged.

## Deploy notes
- No deploy steps. No migrations, no config, no API shape change.

## Risk / rollback
- Risk: none expected; Pydantic already used the surviving declarations. Rollback by reverting the commit.
