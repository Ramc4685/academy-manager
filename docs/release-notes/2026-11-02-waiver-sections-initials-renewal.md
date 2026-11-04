# waiver-sections-initials-renewal

PR: #1111

## What changed
A waiver can now be written as a sectioned agreement. In the waiver body, a line such as `## Assumption of risk [initials]` starts a section; `[initials]` makes the signer initial it, `[adult]` marks the release a participant 18 or over signs, and `[minor]` the parent/guardian release. The child's date of birth on the signing day picks the path: under 18 signs the shared and `[minor]` sections, 18 or over the shared and `[adult]` sections. A waiver with age sections cannot be signed for a child without a date of birth (the Waivers page links to the profile; registration asks the parent to go back to the child step), and a minor-path signature stops counting once the participant turns 18. Initials and the signing path are stored on the signature and shown on the signed copy. Admins can now set how long a signature lasts when assigning a waiver: until the text changes (as before), renew every N months, or valid until a date. A lapsed signature shows as "Outdated" to the parent and "EXPIRED" to staff. Waivers without `##` headings behave exactly as before.

## Deploy notes
No migration: renewal settings and initials are new optional fields, and existing signatures and assignments read as "never expires" with no initials. Deploy after (or with) the waiver explicit-signing PR it is stacked on. To use it for BLNO, paste the participation agreement with `##` headings into a new draft version, publish it, and set "Renew every 12 months" in Assign. Families who signed the old version are asked to sign the new one, as with any new version.

## Risk / rollback
Medium-low. The parent Waivers page and the registration waiver step now render sections and collect initials; the server re-checks initials and the date-of-birth path before saving anything, so a signing act is all-or-nothing. Age uses the UTC calendar date, so a birthday can flip a few hours early or late. Staff do not yet see a "re-sign at 18" flag (the parent does). Revert this PR to roll back; signatures recorded meanwhile keep their extra fields harmlessly.
