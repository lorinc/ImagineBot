# /wrap — session wrap

Close out the current session so the next one can resume without this conversation.

## What to do

Read `.claude/SESSION.md` and skim `git status` / recent diffs to understand what
happened. Then update the three operational files below — but only where there is
something real to write. Skip any step where there's nothing meaningful to add.

Write files directly without asking for approval. After writing each file, show the content that was written so the user can review and correct post-hoc.

### .claude/HEURISTICS.log

For each error, dead-end, or non-obvious environmental finding from this session,
append an entry following the format in the file header.

- PREVENTED_BY is the most important field — make it a structural check, not advice
- If nothing worth logging: say so, skip this step
- **Append using Bash (`cat >> .claude/HEURISTICS.log << 'EOF' ... EOF`), never Edit or Write.**
  A PreToolUse hook blocks Edit/Write on this file. Using Bash is the only valid path.

### .claude/SESSION.md

Update to reflect end-of-session state. The NEXT_SESSION block is the most important
part: it must be specific enough for a cold-start session to begin within two minutes.
Use copy-paste runnable commands, not narrative.

Set HEURISTICS_WRITTEN: yes / no accordingly.

### src/<service>/ARCHITECTURE.md

For each service you touched this session, update its `ARCHITECTURE.md` if the session
changed anything about its structure, interfaces, or key invariants. Write from the
perspective of a new engineer reading cold: components, data flow, external dependencies,
and any sharp edges. Do not log session history or bug narrative here — only current truth.

- Only update services you actually touched
- If the file doesn't exist yet and you changed that service, create it
- If nothing structural changed: skip

### docs/PROJECT_PLAN.md

If a phase completed, started, or was significantly scoped this session, update the
relevant section. Add a DONE entry with the date. Do not record session details or
bug fixes here — those belong in HEURISTICS.log.

## What not to do

- Do not update CLAUDE.md with session history — it holds structure, not state
- Do not summarise what you did — write what the next session needs to know
- Do not invent heuristics entries if nothing went wrong
