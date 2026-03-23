---
name: heuristics-entry
description: Write a heuristics.log entry. Use at the end of any session, after any bug fix, or whenever a dead end is discovered.
---

# Skill: Write a heuristics.log entry

heuristics.log is append-only. It accumulates the real cost of every failure so that
future sessions pay less. A session that ends without writing heuristics has discarded
whatever it learned.

## When to use this skill
- End of any session where something didn't work as expected
- Any time a dead end was explored (even briefly)
- After fixing a bug — record what caused it and what would have prevented it
- After a spike — record any options that were rejected and why

## Format
Append to `heuristics.log` in the repo root. Never edit past entries.

```
[YYYY-MM-DD HH:MM]
CATEGORY: CONTRACT_VIOLATION | ENV_PARITY | TRANSACTION_BUG | PATH_BUG | UI_BUG | AUTH_BUG | CONFIG_BUG | RETRIEVAL_BUG | ACCESS_BUG | OTHER
SERVICE: [gateway | ingestion | knowledge | security | auth | access | channel_web | cross-cutting]
TASK: [one sentence — what was being built when this was discovered]
SYMPTOM: [what was observed — what the user saw, what the logs said]
ROOT_CAUSE: [actual cause — not "it didn't work", but WHY]
PREVENTED_BY: [what structural change would have caught this automatically — hook, contract test, CI step, invariant in CLAUDE.md]
SOLUTION: [what actually fixed it]
DEAD_ENDS: [what was tried that didn't work, and a one-line reason for each]
```

## The most important field: PREVENTED_BY
This is the reason the log exists.
After writing PREVENTED_BY, ask: has that prevention been implemented?
- If it's a hook → add it to `.claude/settings.json`
- If it's a contract test → write it (use contract-test skill)
- If it's an invariant → add it to the service CLAUDE.md
- If it's a CI check → add it to `.github/ci.yml`

If PREVENTED_BY is "nothing — this was a one-off", that's a valid answer.
But think carefully before writing it.

## Example entries

```
[2024-01-20 14:32]
CATEGORY: CONTRACT_VIOLATION
SERVICE: gateway
TASK: Adding session_id to query response
SYMPTOM: Frontend showing undefined for session display — field was present in tests but missing in actual responses
ROOT_CAUSE: Field was named session_id in QueryResponse but serialised as sessionId by a custom alias. Frontend expected snake_case. Tests only checked for field existence, not serialisation.
PREVENTED_BY: Contract test that serialises a real QueryResponse and checks the JSON key names, not just model_fields.
SOLUTION: Removed custom alias. Standardised on snake_case throughout.
DEAD_ENDS: Tried adding model_config with alias_generator — this made it worse because it aliased all fields.

[2024-01-22 09:15]
CATEGORY: CONFIG_BUG
SERVICE: channel_web
TASK: Deploy to staging
SYMPTOM: 500 on all requests after deploy. Worked locally.
ROOT_CAUSE: SESSION_SECRET env var not set in Cloud Run staging config. Python raised at startup but Cloud Run showed it as a crash loop with unhelpful error.
PREVENTED_BY: config.py raising with explicit message "SESSION_SECRET is required" on startup. The Cloud Run logs would then show the actual cause.
SOLUTION: Added SESSION_SECRET to Cloud Run env vars via gcloud CLI.
DEAD_ENDS: Checked application code for hours before checking Cloud Run config.
```

## After writing the entry
Update SESSION.md: set HEURISTICS_WRITTEN: yes.
