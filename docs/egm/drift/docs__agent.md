## docs/agent/README.md

No drift detected.

Resolved in the same change: `.claude/workflows/fix-issue-batch.js` passed `model: 'sonnet', effort: 'medium'` alongside `agentType: 'risk-reviewer'`, which overrode the risk reviewer's pinned Fable/high model that `docs/agent/agent-roles.md` describes. The security lens now omits `model`, so the agent's pin applies.

All 7 files listed at README lines 7-13 exist.
