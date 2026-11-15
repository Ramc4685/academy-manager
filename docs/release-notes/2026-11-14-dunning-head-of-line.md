# dunning-head-of-line

PR: #1165

## What changed
- Billing: one autopay charge that fails to start (for example "no saved Stripe card") no longer stops every other autopay charge in the same run. The parked charge sorted to the front of the queue (an empty next-attempt time sorts first in Mongo), and the old "stop when only parked invoices are left" guard ended the run after one repeat. Since the Nov 8 run, three BLNO November autopay charges sat due and never ran while one family's failing charge was retried hourly. The worker now skips invoices it already parked this run and keeps going. Regression tests cover the worker loop and the real Mongo claim query.

## Deploy notes
No migration. On the first hourly tick after deploy, the three starved November charges ($200 in total) will be attempted automatically, with no manual action. The one family whose charge fails with "no saved Stripe card" keeps parking until a card is re-saved; that is a separate issue.

## Risk / rollback
Low. Only the order in which charges are claimed within one run changes; eligibility, idempotency keys and retry budgets are untouched. Roll back by reverting the PR.
