## Why

Every strategy's `propose` takes the hypothesis plus a fixed list of
per-round inputs: flag changes, service, stale entry keys and deployments. Each
new input has been one more parameter on all 8 strategies, `propose_action`,
`what_each_would_do` and their three callers. FM-33 is about to add another,
the recorded GPU placement.

## What Changes

- A `Circumstances` value in `argus_core.models` carries the per-round inputs:
  `service`, `flag_changes`, `stale_entry_keys`, `deployments`.
- `MitigationStrategy.propose`, `propose_action` and `what_each_would_do` take
  the hypothesis (or candidates) and one `Circumstances`. **BREAKING** for
  their callers.
- The orchestrator builds `Circumstances` in one place. A flag history nobody
  could read still yields no circumstances, and nothing is proposed.
- `mitigate()` (`agent_mitigation/mitigating.py`) is removed. Nothing has
  called it since the §13 gate split proposing from taking.
- No behaviour changes. The placement field arrives with FM-33.

## Capabilities

### New Capabilities
- `mitigation-circumstances`: what a strategy is handed, and when nothing is
  handed at all.

### Modified Capabilities

None.

## Impact

- `argus_core.models`: new `Circumstances`.
- `agent_mitigation`: `strategies.py`, `actions.py`, `__init__.py`;
  `mitigating.py` deleted.
- `orchestrator`: `walk/candidates.py`, `choosing.py`, `investigating.py`,
  `proposing.py`.
- Tests (hand-applied): `test_strategies.py`, `test_actions.py`,
  `test_candidates.py` rewritten; `test_mitigating.py` deleted.
