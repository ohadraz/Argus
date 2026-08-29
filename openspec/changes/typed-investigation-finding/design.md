## Context

`Verdict` (in `argus_core.anthropic_llm`) is the wire shape the model fills in:
`summary`, `cause_type`, `confidence`, `supporting_evidence`. `to_hypothesis`
joins it to an incident. Nothing in that shape names *which* flag - the flag
appears only inside `summary` prose and inside quoted evidence lines.

`agent_mitigation.actions.propose_action(hypothesis, flag_changes)` therefore
ignores the hypothesis except for its `cause_type`, and picks the flag with
`_the_one_changed_flag`: latest change per flag, and `None` unless exactly one
flag is left. That is the escalation seen in practice - two flags in the
window, an Investigator that named one of them at 0.92, and no action taken.

The rule that produced this shape was "never take a write target from model
prose", which remains right. What this change separates is *naming* a target
from *choosing among targets the provider itself reported*.

## Goals / Non-Goals

**Goals:**

- The Investigator's conclusion reaches Mitigation as data, not prose.
- Mitigation stops deriving the culprit and starts confirming one.
- An environment with several recently-changed flags resolves correctly when the
  Investigator identified the right one.
- No regression when the hypothesis names nothing - including for every existing
  recording replayed by `e2e_replay`.

**Non-Goals:**

- Ranked multiple hypotheses and the attempt-next-hypothesis loop. Separate
  change, dependent on this one.
- Subjects for causes other than a feature-flag toggle. The field is general;
  only the flag path reads it, because only the flag path has an action.
- Re-recording the Anthropic double. Existing recordings carry no subject and
  exercise the fallback, which is worth keeping covered.
- Distinguishing Argus's own reverts from a human's in the provider's history.
  Still blocked on the credential model, still unrelated.

## Decisions

**The field is called `subject`, and it is a plain string.** Not `flag`: the
`Hypothesis` is a domain object shared by every cause type, and a field named
for one of them would be dead weight on the others and a lie on the next one. A
string rather than a typed union, because the meaning of the string is already
fixed by `cause_type` - the pair `(FEATURE_FLAG_TOGGLE, "monthly-spend-feature")`
is unambiguous, and a union would encode the same fact twice.

**A subject requires a cause; a cause does not require a subject.** The existing
validator pairs `cause_type` and `confidence`; a sibling rule rejects a subject
with no cause. The reverse is legitimate - a bad deployment is a real cause with
nothing this system can name as its subject yet.

**Mitigation verifies, and the provider still authorises.** The subject selects
*among* `flag_changes`; it is never used as a flag name to write to directly.
So a hallucinated name matches nothing and escalates, exactly as an invented
name should - and the direction of the revert continues to come from the
recorded change, never from the model's prose, which may describe it backwards.

**A named subject that matches nothing escalates rather than falling back.** The
alternative - ignore the unmatched name and apply the single-change rule - would
act on a flag the Investigator did *not* blame while its stated conclusion went
uncorroborated. Two authorities disagreeing about the same incident is a human's
call.

**The fallback is kept, not replaced.** A hypothesis naming no subject still
resolves through `_the_one_changed_flag`. This keeps every committed recording
meaningful, keeps the deterministic path exercised by tests, and means the model
naming a subject is an improvement rather than a dependency.

**The wire field is optional, though every other field on `Verdict` is
required-and-nullable.** That pattern exists to stop a model omitting a field
instead of deciding, and it is right for `confidence`. Here it would also reject
every committed recording, since none carries the field - a replayed verdict
would come back `MalformedVerdict` and the offline suites would lose their
evidence to buy nothing. A live model is steered by the field's description
instead, and one that omits the field says exactly what null says.

**The prompt constrains the name to the evidence.** The evidence already
contains the flag-evaluation log lines, so the model is selecting a token it was
shown rather than recalling one. Combined with provider verification, that is
two independent checks on a value that ends in a write.

**The column is nullable and added to `hypothesis`.** The record of an incident
should say what was blamed. `CREATE TABLE IF NOT EXISTS` never alters an
existing table, so this lands with the schema the way every other column has -
`e2e` teardown drops the volume, and no migration tooling is introduced for it.

## Risks / Trade-offs

**The model now influences which flag is written to.** Mitigated by two
independent gates: the name must appear in the provider's recorded changes, and
the tier gate still rejects any action without an undo descriptor. The blast
radius of a wrong-but-real name is one flag revert, which is reversible and
recorded - and the verdict machinery undoes it when the symptom persists.

**Existing recordings drift further from what the live model returns.** They
already replay by seeded name rather than by prompt, so `e2e_replay` proves the
pipeline and not the verdict; a recording with no subject now also exercises a
different branch than production will. The mitigation is that this branch is the
fallback and must keep working anyway, so the coverage is not wasted - but the
gap is worth naming, and re-recording remains a live question.

**A prompt asking for one more field is a prompt change.** Cause-detection
quality can move for reasons unrelated to the field. The `eval` session is the
instrument for that, and it costs real money to run; this change does not
require it, but a drift in confidence after landing should be checked there
rather than argued about.
