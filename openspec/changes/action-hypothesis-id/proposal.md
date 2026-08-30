## Why

An `action` row does not record which hypothesis it was taken for. Argus knows - the mitigation node holds the candidate it is acting on at the moment it writes the row - and then throws that knowledge away, leaving consumers to recover it by matching the flag name the action and the hypothesis happen to share.

That string match works only because of an unrelated rule: the walk never acts on the same subject twice within one incident. So the link between a decision and the act carried out for it survives by accident of a constraint that exists for another reason entirely, and would break silently the day that constraint is relaxed.

Nothing reads the `action` table yet - `actions.py` is write-only and the postmortem is still a stub - which is exactly why now is the moment. The incident UI is the first consumer that needs the link, to show "this candidate was tried, this action was taken, this was the verdict". Recording it before anything reads it means no consumer is ever written against the subject match, and none has to be unwound later.

## What Changes

- **`action` gains a `hypothesis_id`**, a real foreign key to the hypothesis the action was taken for.
- **The mitigation node passes the candidate it is acting on** when it records the action - it already holds it.
- **The first consumer, the incident UI, follows the key** rather than being written against the subject match and corrected afterwards.
- The column is **nullable**, because not every action has a candidate behind it worth asserting - not because old rows need accommodating. No database outlives a run, so there are no old rows.

## Capabilities

### Modified Capabilities
- `mitigation-retry-walk`: an action recorded during the walk SHALL name the hypothesis it was taken for, rather than being associated with one by shared subject.

## Impact

- **`modules/argus_core/src/argus_core/schema.py`** - one nullable column on `action`, with a foreign key to `hypothesis`.
- **`modules/orchestrator/src/orchestrator/repository/actions.py`** - `record` takes the hypothesis id.
- **`modules/orchestrator/src/orchestrator/graph.py`** - `_record_action` and its call site in the mitigation node thread `state.hypothesis.id` through.
- **No migration** - every stack starts from `docker compose down -v`, so the schema is created fresh on each run and the column simply joins the `CREATE TABLE`. Nothing alters, nothing backfills.
- No change to the agents' behaviour, the MCP servers, the prompts, or the recordings. Nothing the model sees changes.
