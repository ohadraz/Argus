## Why

A walk resumed after its worker died, finding an action claimed with no outcome,
asks the flag provider's log whether the change landed - for every action that
leaves something to put back, rollback, scale-out and the autoscaler pin
included. The log knows nothing of a deployment: asked about a "flag" named after
the application it finds no such change, the walk reads that as the change never
having landed, and acts a second time on a deployment the dead worker may already
have changed - recording what the first attempt left as what there is to put
back.

## What Changes

- The flag provider is asked only about an action that goes through it. A
  resumed claim on any other action - a rollback, a scale-out, a pin, as already a
  restart - escalates as a change nothing can account for.

## Capabilities

### New Capabilities

None.

### Modified Capabilities
- `flag-revert-mitigation`: the requirement settling an unanswered claim by the
  provider's record is limited to flag actions, and says what happens to every
  other kind.

## Impact

- `orchestrator`: `walk/mitigating.py`, and its test.
