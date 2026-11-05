# roster-import-copilot

PR: #1136

## What changed
On the Families page, a CSV whose header is not the five import columns can now be mapped with an AI helper: "Map columns with AI" asks the model for a column mapping, the admin edits it in a table, "Use this mapping" rewrites the file in the browser and runs the existing check and import steps, so the dry run and the import button remain the approval gate. By default the model sees only the column headers and five sample rows masked to their shape (letters become a, digits become 9); an owner can let it see real values with a new switch under Settings > Notifications, "AI import helper". Every request is recorded in `ai_calls` and refused once the academy's monthly cap is reached.

## Deploy notes
No migration and no new env vars. The feature stays dark until `V2_AI_ENABLED` and `V2_ANTHROPIC_API_KEY` are set; until then the route answers 503 `Ai.Disabled` and the button is hidden because `GET /admin/ai/status` (slice B1) is absent or says disabled. `ai.share_import_values` on the academy document is read as off when absent.

## Risk / rollback
If wrong, an admin could be shown a bad column mapping; nothing is imported without the existing dry run and the admin's second look, and a mapping the model gets wrong is corrected in the table before any row is checked. With the sharing switch on, the first five rows of a spreadsheet (names, emails, phones) are sent to the model provider; the switch is owner-only and off by default. Roll back by reverting the PR; the `ai_calls` rows and the settings key are harmless left in place.
