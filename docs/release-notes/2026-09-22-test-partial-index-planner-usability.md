# test-partial-index-planner-usability

PR: #907

## What changed

- New backend test (`backend/v2/tests/contract/test_partial_index_planner_usability.py`, #894 step 2) that asks a real MongoDB whether every partial index the migrations build actually serves a lookup on its keys. It replays all migrations into a throwaway database on the CI MongoDB 8.0 service (the same major version as production), seeds a few rows per index, and checks with a hinted `explain()` that an equality lookup reads one index key rather than walking the whole index. The `{"$type": "string"}` shape that made 34 indexes useless for reads (#878) walks the whole index; a probe test builds one on the fly to prove the check fails on it. Nine hot-path lookups from #878 (Stripe webhook keys, attendance marking, the checkout webhook's application lookup, invoice number) are also asserted to be won by the index built for them, so a query rewritten into a shape the planner cannot use fails too.
- Why: the drift audit compares index definitions and the unit-test database fake evaluates neither partial filters nor query plans, so nothing could catch #878 before production did. This closes that gap, and it is only trustworthy now that CI runs the production MongoDB version (#899).
- The one index that exists purely to enforce uniqueness (`message_deliveries.provider_message_id`) is allowlisted by name with the reason; the test fails if the allowlist goes stale in either direction.

## Deploy notes

None. Test-only. The test skips itself when no `mongod` is reachable, so the suite still runs on a machine without one; CI always has one.

## Risk / rollback

None to the product. Adds about 30 seconds to the backend test job (two migration replays on a real database). If it ever blocks CI for a reason that is not a real defect, `UNIQUENESS_ONLY` in the test is the documented escape hatch, one line per index with a reason.
