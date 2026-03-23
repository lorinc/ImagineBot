---
name: new-feature
description: TDD protocol for building a new feature in any service. Use when PHASE is IMPLEMENT and the spike for this service is complete.
---

# Skill: Build a new feature (TDD protocol)

## Prerequisites (verify before starting)
- [ ] SESSION.md exists with PHASE: IMPLEMENT
- [ ] The relevant service CLAUDE.md has been read this session
- [ ] No open SPIKE REQUIRED warning in the service CLAUDE.md
- [ ] IN_SCOPE in SESSION.md lists exactly the files to be touched
- [ ] ACCEPTANCE in SESSION.md is observable and specific

## Steps

### 1. Write the contract test first
Before writing any implementation:
- If a new model is involved, write the contract test (see contract-test skill)
- Run it: it should fail (model doesn't exist yet) or pass (model exists, contract confirmed)

### 2. Write the unit test
In `tests/unit/test_[service]_[feature].py`:
- Test the business logic in isolation
- Mock all external dependencies (HTTP calls, Firestore)
- Test the happy path and at least one error path
- Run it: it should fail (implementation doesn't exist yet)

### 3. Write the minimum implementation
- Write just enough code to make the unit test pass
- Follow the service pattern documented in the service CLAUDE.md
- Do not add code that isn't tested

### 4. Run contracts + unit
```bash
pytest tests/contracts/ tests/unit/ -v
```
All must pass before continuing.

### 5. Write the integration test
In `tests/integration/test_[service]_[feature].py`:
- Uses real Firestore emulator
- Tests the full request-response cycle
- Uses unique IDs to avoid state pollution
- Cleans up in teardown

### 6. Run integration tests
```bash
pytest tests/integration/test_[service]_[feature].py -v
```

### 7. Manual verification (ACCEPTANCE criterion)
Do not trust your own test output alone. Verify ACCEPTANCE as stated in SESSION.md.
If ACCEPTANCE is "staging returns correct data" — deploy to staging and check.
If ACCEPTANCE is "endpoint returns correct JSON shape" — call it with curl/httpx.

### 8. Update documentation
- Service CLAUDE.md: update module map if new files were added
- COMPONENTS.md: add new route/model/service to inventory
- DELIVERY.md: append delivery row
- If a new model field: update the field contract table in service CLAUDE.md

### 9. Write heuristics entry
If anything didn't work as expected (even briefly), write a heuristics.log entry.
Update SESSION.md: HEURISTICS_WRITTEN: yes.

### 10. Commit
```bash
git add [files in IN_SCOPE only]
git commit -m "[service]: [feature] — [one line description]"
```

Commit message format: `[service]: [what was built] — [tests: n passing]`

## If any step is blocked
Update SESSION.md ATTEMPT to n+1.
If this is attempt 3: STOP. Write heuristics. Declare "needs fresh session."
Do not attempt a 4th time in the same session.
