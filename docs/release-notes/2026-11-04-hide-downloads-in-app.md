# hide-downloads-in-app

PR: #TBD

## What changed
Inside the iOS and Android app, actions that download a file or open the print dialog are hidden, because the app's web view has nowhere to put the file and ignores print: the CSV exports on Reports (QuickBooks journal, deposit slip, refunds, revenue by category), the coach "Export audit" button, the family import template download, and "Print or save as PDF" on certificates and signed waivers. The parent certificate keeps "Share with family". Uploading a CSV still works in the app. Nothing changes in a web browser.

## Deploy notes
Frontend only; ships with the next frontend deploy and needs no new app build (the app loads the deployed site).

## Risk / rollback
Admins on a phone use the website for exports and printing. Detection reads the `window.Capacitor` global the app injects, so a browser never hides anything. Revert this PR to show the buttons again.
