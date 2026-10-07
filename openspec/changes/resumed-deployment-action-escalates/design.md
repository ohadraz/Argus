## Context

`walk/mitigating.py` `_what_the_earlier_attempt_left` asks `change_landed` - bound
to `argus_changed_flag_since`, the flag provider's log - about every action kind
in `leaves_something_to_put_back`, which since the deployment actions arrived
includes rollback, scale-out and the pin.

## Goals / Non-Goals

**Goals:** a resumed deployment action is never acted on twice on the flag log's
word.

**Non-Goals:** reading the deployment platform to settle a resumed claim (a
rollback could be found in Argo CD's history by Argus's actor; a scale-out or pin
leaves no history). Escalating is the safe answer, and a worker dying mid-action
is rare enough not to need a better one yet.

## Decisions

### D1. Ask by platform, not by whether something is left to put back
The question is put only where `the_platform_of(action_type)` is the flag
provider. *Alternative:* list the flag kind explicitly - rejected, it is the
platform whose log is being read, and a second flag action would otherwise be
left out.

## Risks / Trade-offs

- [An escalation where a re-take would have been safe] → a human looks at a
  deployment the dead worker may or may not have changed, which is the honest
  state.
