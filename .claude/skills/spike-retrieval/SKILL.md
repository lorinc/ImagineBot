---
name: spike
description: Run a structured spike to resolve an architectural or technical decision. Use when SESSION.md PHASE is EXPLORE and a spike document needs to be written.
---

# Skill: Run a spike

A spike is a time-boxed EXPLORE session that produces a decision document.
No production code is written. No commits are made.

## When to use this skill
- A `SPIKE_PENDING` item exists in the root CLAUDE.md
- A CLAUDE.md says "SPIKE REQUIRED BEFORE IMPLEMENTATION"
- You are in PHASE: EXPLORE

## Steps

### 1. Open SESSION.md
Confirm PHASE is EXPLORE. If not, stop and ask.
```
PHASE: EXPLORE
TASK: Spike — [topic]
SERVICE: [which service this spike informs]
ROLLBACK_TO: clean (no writes during a spike)
ATTEMPT: 1 of 1  (spikes don't retry — they just gather information)
ACCEPTANCE: docs/spikes/[topic].md exists, contains a decision, and lists dead ends
HEURISTICS_WRITTEN: no
```

### 2. Read before writing
Read ALL of the following before forming any opinion:
- Root CLAUDE.md (especially the spike questions listed there)
- The relevant service CLAUDE.md (it lists what the spike must answer)
- Any existing code in that service directory
- `heuristics.log` — look for any entries with CATEGORY matching this domain

### 3. Research options
For each option being considered:
- What is the implementation complexity?
- What does it require as a dependency?
- Does anything in heuristics.log warn against it?
- What does "this goes wrong in sprint 5" look like?

### 4. Write the spike document
Create `docs/spikes/[topic].md` using the template in docs/CLAUDE.md.
Sections required:
- Question (one sentence)
- Options considered (minimum 2, with pros/cons)
- Dead ends (what was considered and rejected, and why)
- **Decision** (be direct — say which option and why)
- Implementation notes

### 5. Update heuristics.log
If any dead ends were discovered during research, write a heuristics.log entry.
Use CATEGORY: OTHER if none fits. The PREVENTED_BY field is mandatory.

### 6. Update the service CLAUDE.md
Remove or replace the "SPIKE REQUIRED" warning.
Fill in the implementation details the spike resolved.

### 7. Update root CLAUDE.md
Remove the spike from SPIKES_PENDING.

### 8. Update SESSION.md
Set HEURISTICS_WRITTEN: yes (even if the entry was "no dead ends found").
Note context percentage from `/cost`.

## What NOT to do during a spike
- Do not write production code
- Do not commit anything
- Do not install packages to test them (read docs instead)
- Do not start the next task in the same session (end cleanly)
