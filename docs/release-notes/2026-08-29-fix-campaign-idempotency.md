# campaign-idempotency

PR: #566

## What changed
POST /campaigns was non-idempotent: every invocation of `SendCampaign.execute`
minted a fresh `campaign_id` and sent one email per resolved recipient, with no
idempotency key, claim, or dedup. A retried request — a proxy timeout after the
emails already left, a double-click, a frontend retry — re-emailed the entire
audience. Worse, per-recipient `Delivery` rows were only persisted after the
whole send loop, so a process restart mid-loop left the campaign stuck in
SENDING with zero delivery records; the admin UI showed nothing sent and
invited the second (double-sending) click.

Campaigns now carry an `idempotency_key`: the client may supply one on
`SendCampaignRequest`, and when omitted the backend derives one as a SHA-256
hash of academy + sender + subject + body + audience descriptor, so an
identical retry always resolves to the same key. `SendCampaign` claims the key
before sending via `CampaignRepository.try_claim`, an insert-first write
against a new unique partial index `(academy_id, idempotency_key)` — the same
pattern as the coach-digest `try_claim` guard. A lost claim reads back the
winning campaign and returns its delivery counts with `deduplicated: true`,
sending zero emails. The full QUEUED delivery batch is now persisted before
the send loop (`save_many` upserts by `delivery_id`), so a crashed run leaves
a visible, countable roster instead of an invisibly half-sent campaign.

## Deploy notes
Migration `0155_campaign_idempotency_key_index` creates the unique partial
index on `message_campaigns`. It is partial on `idempotency_key` being a
string, so pre-existing campaign documents (which lack the field) neither
block each other nor the index build. The API change is additive: the new
request field is optional and the response gains a `deduplicated` boolean the
existing frontend ignores.

## Risk / rollback
Content-derived keys mean an admin who deliberately sends the *identical*
subject + body to the *same* audience twice now gets a deduplicated response
instead of a second send; sending again requires changing the content (or the
frontend passing a fresh `idempotency_key`). This is judged safer than the
double-send it prevents. The claim is per-academy, so identical campaigns in
different academies are unaffected. A concurrent duplicate that loses the
claim while the winner is mid-send returns the winner's in-progress counts
(possibly zero sent yet) rather than blocking — acceptable, since no extra
email leaves. Roll back by reverting the merge commit; the index and any
stamped `idempotency_key` fields are inert under the old code, which simply
ignores them.
