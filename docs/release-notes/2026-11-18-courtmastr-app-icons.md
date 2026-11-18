# courtmastr-app-icons

PR: TBD

## What changed
The web app now uses the CourtMastr logo ("Earned Stripes", chosen 2026-11-03) instead of the house academy's yellow "B". That covers the browser favicon, the PWA/home-screen icons and the iOS apple-touch icon. The platform-host login and register header, the CourtMastr landing page, the franchise (owner) shell and the "Bookings and payments by CourtMastr" footer credit also switch from a shuttlecock or monogram to the logo. Academy logos (`logo_url`) and academy monograms on academy hosts are unchanged.

## Deploy notes
- None for the web. Installed PWAs and browsers may keep the cached old icon until they refresh it.
- The native iOS and Android icons and splash in `mobile/` already used this logo, so nothing changes there. Store builds pick it up from those assets as they are.

## Risk / rollback
- Risk: low. This PR changes static images and presentational components only, with no data or API changes.
- Rollback: revert the PR.
- Phone and desktop before/after screenshots (platform login, platform landing, tenant footer, icon set) were taken locally and reviewed.
