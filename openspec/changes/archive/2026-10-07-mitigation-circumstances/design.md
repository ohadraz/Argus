## Context

`MitigationStrategy.propose(hypothesis, flag_changes, /, service,
stale_entry_keys=(), deployments=())`. `propose_action` and
`what_each_would_do` repeat the list, and three orchestrator nodes assemble it
from the alert and the round's reads, each with its own `or ()`.

## Goals / Non-Goals

**Goals:** one value carries every per-round input, so the next one (FM-33's
placement) is a field, not a signature change.

**Non-Goals:** the placement itself; any behaviour change; the Argo CD adapter.

## Decisions

### D1. `Circumstances` lives in `argus_core.models`
Two modules name it - `agent_mitigation` reads it, `orchestrator` builds it -
so it is a contract. A frozen dataclass like `Findings`: an in-process value,
never serialized, so nothing for pydantic to validate. `stale_entry_keys` and
`deployments` default to empty, as they do now.

### D2. The hypothesis stays outside, the service goes inside
The hypothesis varies per candidate within one `what_each_would_do` call; the
rest is fixed for the round. The service is per-round too, and keeping it named
beside the bundle would leave two ways of passing an input.

### D3. `propose(hypothesis, circumstances, /)`
Both positional. The protocol's existing reason holds: a stand-in that ignores
an input names it `dont_care_*`, which a protocol fixing names forbids.
`propose_action(hypothesis, circumstances, strategies=DEFAULT_STRATEGIES)`;
`what_each_would_do(candidates, circumstances)`.

### D4. Built in one place; unreadable history is `None`
`the_circumstances(alert, flag_changes, deployments) -> Circumstances | None`
in `orchestrator/walk/candidates.py`, used by all three nodes. `None` where the
flag history could not be read, which `what_each_would_do` and the proposal
node already answer with nothing. The `or ()` for the alert's keys and the
platform's history moves into it.

### D5. `mitigate()` is deleted
No caller outside its own test since the §13 gate split proposing from taking.
Migrating it would keep a second entry point alive for nobody. `ActionTaker`
and `FlagChangeFetcher` existed only as its seams, and go with it.

## Risks / Trade-offs

- Strategy docstrings argue from the old signature ("both parameters are still
  spelled as the protocol spells them"). They are reworded, not left stale.
