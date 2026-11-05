# pipeline-ai-reply-draft

PR: #TBD

## What changed
A contact card on the Pipeline board that has an inquiry message and an email now offers "Draft reply" when AI is on for the academy: the model drafts a short reply from the lead's message, the child's age, the class the lead asked about, the classes the public page shows and the trials-open line, and staff edit the subject and body before an explicit "Send reply". The send goes to the lead through the same prospect send path as the inquiry acknowledgement (opt-out gate, bounce suppression, CAN-SPAM footer) and is logged on the family contact log by the staff member; a lead with no email or a suppressed address is refused. The public inquiry form now says under the message box that sensitive details should be left out and that AI tools may help read and answer messages, with a person reviewing every reply.

## Deploy notes
No migration, no new env vars. The feature stays dark until `V2_AI_ENABLED` and `V2_ANTHROPIC_API_KEY` are set and the academy's platform plan has the `ai` feature; without the plan the draft route answers 403 `Ai.NotEntitled`, and the button is hidden whenever `GET /admin/ai/status` does not say enabled. Every draft writes one `ai_calls` row (feature `pipeline_reply`, prompt `pipeline-reply-v1`, approver = the staff member) and counts against the academy's monthly cap. The send route itself does not need AI: it is an ordinary staff reply.

## Risk / rollback
If wrong, a lead could get a reply with an invented fact: the model only sees the lead's own message, the child's age, the requested class title and the academy's public class lines, a parse step refuses any link other than the academy's public page, and nothing is sent until a staff member reads and submits the text. A draft never reaches a parent on its own. Roll back by reverting the PR; the `ai_calls` rows and contact log entries already written are harmless. Turning `V2_AI_ENABLED` off hides the button and makes the draft route answer 503 while the send route keeps working.
