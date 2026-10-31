# self-host-fonts

PR: #1095

## What changed
The app's three fonts (Manrope, Outfit, JetBrains Mono) are now served from the repo instead of being downloaded from Google Fonts at build time. The 2026-10-29 production frontend deploy for #1093 failed because Next's Google Fonts loader got a response it could not parse, and an E2E run on #1093 failed for the same reason. Pages look the same: these are the latin variable files Google serves, exposed through the same CSS variables.

## Deploy notes
None. No migrations or settings. The next production deploy from main also brings back #1093's backend change: a queued rerun of the older `0b40ce889` run redeployed that backend after `e434e9770`'s frontend failed.

## Risk / rollback
Low. Only the latin subset is bundled (the one we already preloaded), so a rare latin-ext character falls back to the system font. Revert the PR to go back to next/font/google.
