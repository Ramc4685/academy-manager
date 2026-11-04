# parent-push-events

PR: #TBD

## What changed
Four parent emails now also send a push notification to the family's phones in the iOS and Android app, right after the email: a cancelled class date (to every affected family, including make-up and trial kids; opens the parent home), a waitlist seat offer with its claim deadline (opens Requests on that offer; the "offer expired" email does not push), an urgent class announcement (opens Messages; routine announcements do not push), and the dues reminders, both the admin's manual send and the automated past-due sweep (opens Payments; only for parents whose reminder email actually went out). Email stays the record: a push failure is logged and never fails, retries or delays the email.

## Deploy notes
Backend only, no migration. Pushes reach phones only after `PUSH_DELIVERY_ENABLED=true` is set on the API; until then they go to the in-memory stub. Before turning it on, the iOS APNs key must be uploaded to Firebase and Android needs `google-services.json` in the app build, or those phones simply get nothing.

## Risk / rollback
Each push is one FCM call per family after its email, so a large class cancellation takes slightly longer to finish. A family with several phones gets one push per phone. Turn `PUSH_DELIVERY_ENABLED` off to stop all pushes without a deploy, or revert this PR to remove the four hook-ups.
