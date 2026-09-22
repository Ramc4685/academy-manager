# admin-sidebar-groups

PR: #919

## What changed

- The admin sidebar is regrouped into six groups in a fixed order: TODAY (Dashboard, Inbox), CLASSES (Sessions, Pathway), PEOPLE (Students, Families, Users), REACH (Messages), MONEY (Payments, Month close, Billing Health, Expenses, Coach payouts) and ACADEMY (Waivers, Settings, Audit logs). Labels are unchanged; only the grouping and captions move. The Users item is renamed to Staff in a follow-up PR.
- Every nav item now has a stable id; the sidebar test ids are `admin-nav-<id>` rather than derived from the label. Existing ids match the old label slugs, so nothing that selects on them changes.
- A new `badge` icon for the Users item, and the `attend` icon for Waivers.
- Group caption spacing is tighter so six groups still fit a 1280x900 sidebar without scrolling. Phone drawer rows keep their 44px touch height.

## Deploy notes

None. Frontend only, no routes added or removed, no API or data changes.

## Risk / rollback

Low. The change is layout and grouping; every destination is the same. If a coach or admin cannot find something, the order of items inside each group is the old order. Rollback is reverting this squash commit.
