# published-class-calendar

PR: TBD

## What changed
Academies can now set which days have class each month and publish that month to parents. A new admin page, Sessions → Month dates, lists every class date in the chosen month. The admin unticks a class or a whole day and saves. Each unticked date goes through the existing "cancel this date" path: the coach is not paid, and a family is credited only if they end up with fewer classes than they paid for. "Publish {month}" marks the month as final. It can also email each class's families their class and no-class dates as a session announcement.

On the parent calendar, phones now open on a list grouped by month. Each date says "Class" or "No class" with the academy's reason. A month that isn't published yet says its dates aren't confirmed. Wide screens keep the month grid, and a List/Month toggle switches between the two. "Add to my calendar" subscribes the parent's iPhone, Google or Outlook calendar to a private live feed of all their children's classes. A date called off later shows as cancelled in that calendar on its own. The feed covers published months only, or about six months ahead for an academy that never publishes. The parent can reset the link, and old links then stop working.

## Deploy notes
- Migration `0242_calendar_feed_links_index` creates a unique index on the new, empty `calendar_feed_links` collection. It is safe to apply at any time.
- The calendar link is signed with `UNSUBSCRIBE_TOKEN_SECRET`, using its own domain prefix. If that secret is unset, there is no link and no feed, and the "Add to my calendar" button stays hidden.
- Publishing is opt-in. Until an academy publishes a month, parents see every date as before, with an "aren't confirmed yet" note. The feed shows about six months ahead.
- New public route `GET /api/v2/calendar-feed/{token}.ics`, rate-limited to 60 requests a minute per client. The academy comes from the request host, never from the token.

## Risk / rollback
- Risk: the feed carries children's first names and class times to the parent's calendar provider. The link is private and can be reset, and it stops working once the parent's membership loses the parent role.
- Risk: a called-off date can't be restored from Month dates, as with the existing single-date cancel.
- Rollback: revert the PR. The `calendar_feed_links` collection and the `schedule_published_through` policy field are ignored by the old code.
