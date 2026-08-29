## Why

The Investigator identifies the culprit and then throws that answer away. Its
verdict names the flag only inside prose - `summary` and `supporting_evidence` -
so Mitigation cannot read it, and instead re-derives the culprit from the
provider's change history on its own. Where that history holds more than one
changed flag, Mitigation escalates an incident the Investigator had already
solved.

That is not hypothetical. A demo session that stages one flag scenario and then
another leaves both flags in the provider's recent history; the Investigator
names the right one at 0.92 confidence and Mitigation refuses to act, because
from its own narrower view the environment is ambiguous. Every incident after
the first in any environment where two flags moved recently behaves this way.

It is also a structural problem, not only a missing field. Mitigation
re-deriving the culprit *is* a second investigation, which defeats the point of
having an investigation phase: if every phase re-answers the question its own
way, the phases can disagree, and the one that acts is not the one that
reasoned.

## What Changes

- The model's verdict gains a `subject`: the specific thing the named cause is
  about - for a feature-flag toggle, the flag's name - carried as a field
  rather than left in prose. `Hypothesis` carries it onward.
- Mitigation stops searching. It reads the subject from the hypothesis and
  **verifies** it against the provider's recorded changes: does that flag
  appear, and in which direction did it move? The provider still authorises
  every write - a subject the provider never recorded is not acted on.
- Where the hypothesis names no subject, Mitigation keeps today's rule as the
  fallback: exactly one changed flag is the flag, and zero or several escalate.
  Nothing that works today stops working.
- The Investigator's prompt is told to name the subject using an identifier that
  appears verbatim in the evidence it was given, so a name the model invents
  fails verification instead of reaching a write.

**Not in scope**, deliberately: ranked multiple hypotheses and the
attempt-next-hypothesis loop. That change depends on this one - it needs
findings a caller can act on one at a time - and is proposed separately.

## Capabilities

### New Capabilities

None. This sharpens the contract between two existing capabilities rather than
adding a third.

### Modified Capabilities

- `llm-hypothesis-generation`: the verdict schema and the hypothesis it becomes
  carry the subject the cause names, and the prompt constrains that name to one
  present in the evidence.
- `flag-revert-mitigation`: the flag to revert is the one the hypothesis names,
  verified against the provider's recorded changes, rather than derived from
  those changes alone. The existing single-change rule survives as the fallback
  for a hypothesis that names nothing.

## Impact

- `argus_core.anthropic_llm` - `Verdict` gains a field, `to_hypothesis` passes
  it, `SYSTEM_PROMPT` and `build_prompt` explain how to fill it.
- `argus_core.models.hypothesis` - `Hypothesis` gains the field; the
  cause/confidence validator gains a sibling rule (a subject without a cause is
  incoherent).
- `argus_core.schema` and the hypothesis repository - one nullable column, so
  the record of an incident says which flag was blamed, not only that a flag
  was.
- `agent_mitigation.actions.propose_action` - selects by subject first, falls
  back to the single-change rule. Still pure, still no model call.
- `anthropic_double` recordings - existing recordings carry no subject, which
  exercises exactly the fallback path, so `e2e_replay` keeps working unchanged.
  Whether to re-record is a separate decision.
