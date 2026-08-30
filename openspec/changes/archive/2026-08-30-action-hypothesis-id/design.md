## Context

`action` records what was done and what would undo it, but not what it was done *for*. The mitigation node holds the candidate at the moment it writes the row and discards it, so anything that later wants "the action taken for this hypothesis" recovers it by matching the flag name the two share.

Recovering it that way works only because the walk refuses to act on the same subject twice in one incident - a rule that exists to stop Argus retrying a move it has already made, not to keep this association unique. The link would therefore be correct by side effect.

No consumer has had to rely on that yet: `actions.py` has no read side, and the postmortem is a stub that reads nothing. The incident UI proposed next is the first thing that needs it. Taking this change first means the association is recorded before anything is written against the inference - so there is no consumer to unwind, and the walk's no-repeated-subject rule stays a rule about retrying rather than a load-bearing part of the data model.

## Goals / Non-Goals

**Goals:**
- An action names the hypothesis it was taken for, as a foreign key.
- Consumers follow the key instead of comparing subjects.

**Non-Goals:**
- Any migration or backfill. The database is recreated on every run.
- A read path. Nothing consumes the association yet, and a repository read with no caller is code nothing exercises; the change that needs it adds it.
- Changing anything the model sees. No prompt, no recording, no agent behaviour.

## Decisions

### The column is nullable

Not to accommodate old rows - there are none, since no database outlives a run. Nullable states the truth about a row: an action whose candidate is unknown is a different thing from one whose candidate is known, and the schema should be able to say which it is rather than inventing an answer.

### The column is added to the DDL, and nothing migrates

`create_schema` is `CREATE TABLE IF NOT EXISTS`, so a database that already holds an `action` table would never see a new column. That would matter if any database outlived a run - and none does. Every stack starts from `docker compose down -v`, so the schema is created from scratch each time and the DDL is the whole story.

So: the column goes in the `CREATE TABLE`, and there is no `ALTER`, no migration step and no compatibility branch. Argus is not deployed anywhere that holds data between runs, and writing migration machinery for a database that is always empty is machinery nobody can test and everybody has to read.

This is a real constraint rather than an oversight, and it is worth stating plainly: **the schema is disposable**. The day Argus keeps a database across restarts, that assumption breaks and this project needs a migration story - not an `ALTER` bolted onto the DDL.

### The mitigation node passes what it already holds

`_record_action` is called from the node that owns `state.hypothesis`, so the id is threaded through `actions.record` as a required argument rather than looked up. A required argument, not an optional one: a call site that does not know which candidate it is acting for is a bug, and a default would hide it.

### The gate's refusal records no action

When the gate refuses a candidate, no action is taken, so there is no row and nothing to associate. That path is unchanged - this change touches only where an action is actually written.

## Risks / Trade-offs

- **A stack restarted without `-v` keeps the old table and never gains the column** → the symptom is an insert failing on an unknown column, which is loud rather than silent. The fix is the teardown the project already prescribes.
- **A null hypothesis reads as an error rather than as "not recorded"** → consumers treat null as unknown. The UI, the next consumer, should render it as unknown rather than dropping the action from the timeline.
- **A column nothing reads yet can drift from reality unnoticed** → the write path is exercised by `e2e_replay` on every run, so a broken insert fails loudly even before a reader exists.

## Open Questions

None. The one that was here - whether anything already matches actions to hypotheses by subject - was answered by looking: nothing reads the `action` table at all.
