"""What set it off: the change the confirmed cause blamed, the state it left,
the state it went to, when and by whom.

A flag's states are words and said in capitals; a deployment's are revisions,
said as written and cut as git cuts one, since a revision is an identifier and
not a word; and a change of no known kind says its states as they were written.
"""

from __future__ import annotations

from typing import Final, assert_never

from argus_core.models import (
    Alert,
    ChangeKind,
    ChannelReading,
    NoTrigger,
    PostmortemDocument,
    Trigger,
    WhyNoTrigger,
)
from pydantic import BaseModel, ConfigDict

from postmortem_rendering.formatting import as_revision
from postmortem_rendering.lines import Line, Role, Run
from postmortem_rendering.supporting import a_reference


class TriggerSection(BaseModel):
    """The sentence, whether it is only suspected, and whether its states are
    revisions - for a destination that marks either - or, in its place, why a
    confirmed cause came to none (`unestablished`), or the sentence said where
    nothing was confirmed (`absent`)."""

    model_config = ConfigDict(frozen=True)

    line: Line | None
    suspected: bool
    states_are_revisions: bool
    absent: str | None
    unestablished: Line | None


def the_trigger(postmortem: PostmortemDocument, alert: Alert) -> TriggerSection:
    """The trigger said as one sentence.

    Suspected where nothing tested it - the leading candidate's change, which
    an action only recommended would have confirmed or refuted - and said so
    first, so it is read before the change is. A deployment's subject is the
    service it went to.

    Where a confirmed cause came to none, why: "no trigger was established"
    beside a confirmed cause reads as the cause in doubt.
    """
    trigger = postmortem.trigger
    if trigger is None:
        if postmortem.no_trigger is not None:
            return TriggerSection(line=None, suspected=False, states_are_revisions=False,
                                  absent=None,
                                  unestablished=_why_none(postmortem.no_trigger, postmortem))

        return TriggerSection(line=None, suspected=False, states_are_revisions=False,
                              absent="No trigger was established.", unestablished=None)

    deployed = trigger.kind is ChangeKind.DEPLOY
    runs: list[Run] = []

    if trigger.suspected:
        runs += [Run(text="Suspected, not confirmed:", role=Role.STRONG), Run(text=" ")]

    subject = alert.service if deployed else trigger.subject
    noun = " flag" if trigger.kind is ChangeKind.FLAG_TOGGLE else ""
    runs.append(Run(text=subject, role=Role.CODE))

    carrier = next((cited for cited in postmortem.changes_read
                    if cited.label == trigger.carried_by), None)

    if trigger.from_state or trigger.to_state:
        runs += [Run(text=f"{noun} {'was deployed' if deployed else 'went'} from "),
                 _a_state_of(trigger, trigger.from_state, Role.FROM_STATE, postmortem),
                 Run(text=" to "),
                 _a_state_of(trigger, trigger.to_state, Role.TO_STATE, postmortem)]
    elif noun:
        runs.append(Run(text=noun))
    elif carrier is not None:
        # A file a deploy changed moved between no states, and is still a
        # change: said as one.
        runs.append(Run(text=" changed"))

    if trigger.changed_at:
        runs += [Run(text=" at "), Run.a_moment(trigger.changed_at)]

    if carrier is not None:
        # Whoever started the deploy, not whoever wrote the setting: the
        # deploy is the change the record holds.
        runs += [Run(text=", in the deploy of "),
                 a_reference(carrier.change, carrier.short_reference)]
        if trigger.actor:
            runs.append(Run(text=f" that {trigger.actor} started"))
    elif trigger.actor:
        runs.append(Run(text=f", by {trigger.actor}"))

    runs.append(Run(text="."))

    return TriggerSection(line=Line(runs=tuple(runs)),
                          suspected=trigger.suspected,
                          states_are_revisions=deployed,
                          absent=None,
                          unestablished=None)


def _why_none(no_trigger: NoTrigger, postmortem: PostmortemDocument) -> Line:
    """Why the confirmed cause came to no trigger, as one sentence: what it
    blames and what was read of it. Each deploy it names said as the deploy's
    row says it, leading to its commit; what it blames, and a service, said
    as code."""
    confirmed = f"{no_trigger.candidate} was confirmed"
    subject = Run(text=no_trigger.subject or "", role=Role.CODE)
    service = Run(text=no_trigger.service or "", role=Role.CODE)
    deploys = _one_after_another([_a_deploy(label, postmortem) for label in no_trigger.deploys])
    several = "both" if len(no_trigger.deploys) == 2 else "all"

    runs: tuple[Run, ...]
    match no_trigger.why:
        case WhyNoTrigger.CARRIED_BY_SEVERAL_BY_THE_ONSET | WhyNoTrigger.CARRIED_BY_SEVERAL:
            by_then = (" by the time the incident began"
                       if no_trigger.why is WhyNoTrigger.CARRIED_BY_SEVERAL_BY_THE_ONSET
                       else "")
            runs = (Run(text=f"{confirmed}, and the deploys of "), *deploys,
                    Run(text=f" {several} changed "), subject,
                    Run(text=f"{by_then}; which of them set it off is not known."))
        case WhyNoTrigger.CARRIED_AFTER_THE_ONSET:
            noun = "deploy" if len(no_trigger.deploys) == 1 else "deploys"
            runs = (Run(text=f"{confirmed}; the {noun} of "), *deploys,
                    Run(text=" changed "), subject,
                    Run(text=", but after the incident began."))
        case WhyNoTrigger.ANOTHER_SERVICE_S_DEPLOYS_UNREAD:
            runs = (Run(text=f"{confirmed}; it blames "), service,
                    Run(text=", whose deploys Argus did not read."))
        case WhyNoTrigger.NAMES_NOTHING_SPECIFIC:
            runs = (Run(text=f"{confirmed}, but it names nothing specific, so no change could "
                             f"be matched to it."),)
        case WhyNoTrigger.CHANGES_UNREAD:
            runs = (Run(text=f"{confirmed}; {_nothing_matched_and_what_went_unread(postmortem)}"),)
        case WhyNoTrigger.THE_SERVICE_ITSELF:
            runs = (Run(text=f"{confirmed}; it blames "), service,
                    Run(text=" itself and names no change to it."))
        case WhyNoTrigger.NO_DEPLOYS_READ:
            runs = (Run(text=f"{confirmed}, but Argus found no deploys in the window it read."),)
        case WhyNoTrigger.NO_DEPLOY_READ_CHANGED_IT:
            runs = (Run(text=f"{confirmed}, but none of the deploys Argus read changed "),
                    subject, Run(text="."))
        case WhyNoTrigger.NOT_EVERY_DEPLOY_READ_IN_FULL:
            runs = (Run(text=f"{confirmed}; none of the deploys Argus read in full changed "),
                    subject, Run(text=", and Argus did not read all of what "), *deploys,
                    Run(text=" changed."))
        case WhyNoTrigger.NO_DEPLOY_READ_IN_FULL:
            runs = (Run(text=f"{confirmed}, but Argus did not read all of what "), *deploys,
                    Run(text=" changed."))
        case WhyNoTrigger.NOT_TIED:
            runs = (Run(text=f"{confirmed}, but Argus could not tie "), subject,
                    Run(text=" to any change it read."))
        case _:
            assert_never(no_trigger.why)

    return Line(runs=runs)


# What each kind of change unread is said as, by what came of reading it.
_WHAT_WENT_UNREAD: Final = {
    ("deploys", ChannelReading.NOT_ASKED): "did not read the deploys",
    ("deploys", ChannelReading.UNANSWERED): "asked for the deploys and got no answer",
    ("flags", ChannelReading.NOT_ASKED): "did not read the flag history",
    ("flags", ChannelReading.UNANSWERED): "asked for the flag history and got no answer"
}


def _nothing_matched_and_what_went_unread(postmortem: PostmortemDocument) -> str:
    """That no change read was matched to the cause, and beside it - not as
    its reason, since a flag cannot be in the deploys - which kinds of change
    went unread, from the document's own readings. The first alone where it
    carries none."""
    unread = [_WHAT_WENT_UNREAD[(kind, reading)]
              for kind, reading in (("deploys", postmortem.deploys_reading),
                                    ("flags", postmortem.flags_reading))
              if reading is not None and (kind, reading) in _WHAT_WENT_UNREAD]
    nothing_matched = "no change Argus read was matched to it"

    if not unread:
        return f"{nothing_matched}."
    if len(unread) == 1:
        return f"{nothing_matched}, and Argus {unread[0]}."
    return f"{nothing_matched}. Argus {unread[0]}, and {unread[1]}."


def _a_deploy(label: str, postmortem: PostmortemDocument) -> Run:
    """A deploy the sentence names, as its row names it - or by its label,
    where no change read goes by it."""
    cited = next((cited for cited in postmortem.changes_read if cited.label == label), None)

    return a_reference(cited.change, cited.short_reference) if cited else Run(text=label)


def _one_after_another(runs: list[Run]) -> tuple[Run, ...]:
    """Runs said as a list is: "a", "a and b", "a, b and c"."""
    if len(runs) < 2:
        return tuple(runs)

    joined: list[Run] = []
    for position, run in enumerate(runs):
        if position:
            joined.append(Run(text=" and " if position == len(runs) - 1 else ", "))
        joined.append(run)

    return tuple(joined)


def _a_state_of(trigger: Trigger,
                state: str | None,
                role: Role,
                postmortem: PostmortemDocument) -> Run:
    """One end of the trigger's move, playing `role`. A deployment's revision a
    change read names is said as that change's row says it - short, leading
    where it opens - so the document names one revision one way; any other
    state as `_a_state` says it."""
    read = next((cited for cited in postmortem.changes_read
                 if trigger.kind is ChangeKind.DEPLOY and state
                 and cited.change.reference == state), None)
    if read is not None:
        return a_reference(read.change, read.short_reference).model_copy(update={"role": role})

    return Run(text=_a_state(state, trigger.kind), role=role)


def _a_state(state: str | None, kind: ChangeKind | None) -> str:
    """A revision as git shows one, a flag's state in capitals, any other as
    written - a setting's `v2` is not `V2` - and a state nobody recorded as
    unknown."""
    if kind is ChangeKind.DEPLOY and state:
        return as_revision(state)

    said = state or "unknown"
    return said.upper() if kind is ChangeKind.FLAG_TOGGLE else said
