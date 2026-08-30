## 1. Find the consumers

- [x] 1.1 Grep for anywhere an action is matched to a hypothesis by subject or flag name - **nothing does**: `actions.py` is write-only and `agent_postmortem` is a stub that reads nothing. No consumer to unwind

## 2. Schema

- [x] 2.1 Add `hypothesis_id UUID REFERENCES hypothesis(id)` to the `action` table in `argus_core/schema.py`, nullable
- [x] 2.2 No migration: the stack is torn down with `-v` every run, so the DDL is the whole story

## 3. Write path

- [x] 3.1 Propose a test that an action records the hypothesis it was taken for (TDD: proposed in chat, human pastes, then implement)
- [x] 3.2 `actions.record` takes the hypothesis id as a required argument - no default, so a caller that does not know is a compile-time problem rather than a null row
- [x] 3.3 `_record_action` and the mitigation node pass `state.hypothesis.id`
- [x] 3.4 Confirm the gate's refusal path is untouched: it writes no action, so it has nothing to associate

## 4. Read path

Dropped from this change. With no consumer (see 1.1), a repository read added
here would sit uncalled and unexercised until the UI arrives. `argus-incident-ui`
task 1.3 already owns adding `actions.get_by_incident`, alongside the thing that
uses it - and the null-is-unknown handling belongs with the reader, not ahead of
it.

## 5. Checks

- [x] 5.1 `nox -s lint typecheck test_all guard_e2e_boundary integration`
- [x] 5.2 `nox -s e2e_replay` - the walk writes actions on every run, so this exercises the new column end to end
- [x] 5.3 Confirm no recording, prompt or agent behaviour changed - nothing the model sees is in scope
