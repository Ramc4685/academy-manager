# Resend invoice-delivery visibility

PR: #305

## What changed
Successful invoice email sends now persist Resend's provider message ID and
expose a delivery-record link in the admin billing panel. Failed later sends
preserve the last successful provider ID.

## Deploy notes
No migration, environment variable, or manual deployment step is required.
The optional field is persisted through the existing invoice document mapping.

## Risk / rollback
The main risk is linking an invoice to an incorrect Resend delivery record.
Revert PR #305 to stop storing and displaying the ID. Existing optional field
values can remain in Mongo because older code ignores them.
