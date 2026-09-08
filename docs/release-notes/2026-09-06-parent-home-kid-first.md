# parent-home-kid-first

PR: #681

## What changed
The parent home answers the two questions parents actually open the app with
(role-model slice 4): **how are my kids doing, and do I owe anything?**

Home is now **one card per child** — the child's name, their next session with
day, time and venue, how many sessions they attended this month, and their
latest skill milestone. Tapping a card opens that child's skill progress.
Times are shown on the academy's clock, so a parent travelling sees the class
time the class actually starts at.

Billing only appears when it is real: a **balance banner sits above the cards
only when an invoice is due or a payment has failed**, saying what is owed and
by when, with a single Pay action. When nothing is due, Home shows no billing
content at all. Payments keep their own tab.

The single-child hero with its chip switcher, the three metric tiles and the
separate "latest note" and "next class" cards are gone — the per-child card
replaces all four. Requests, recent activity and the academy contact block are
unchanged, below the cards. Tabs are unchanged: Home · Children · Payments ·
Progress.

Behind it, one new read — `GET /api/v2/parent/home` — returns every child's
card and the family balance in a single request. Without it a family with
three children would have cost seven round trips to draw one screen.

## Deploy notes
**No migration.** No new environment variables.

The new route is additive and no existing parent endpoint changed shape, so
backend and frontend can deploy in either order. If the frontend ships first
it will see a 404 on `/parent/home` and Home renders its error state; ship the
backend first to avoid that window.

Nothing changes for coaches, admins or owners.

## Risk / rollback
Low. Parents see a reordered Home built from data they could already see; no
money moves, no schema changes, no background jobs.

Revert the PR to restore the previous Home. The new endpoint becomes unused
rather than broken, and because no existing endpoint was modified, the old
page's reads all still work.

The one behaviour worth watching is the balance banner's silence: when nothing
is due, Home deliberately shows no balance at all. A parent who previously
glanced at Home to confirm they were paid up now confirms it by the absence of
the banner, or on the Payments tab.
