"""Everything a walk is supplied with.

`ports` says what each collaborator's shape is; this says that the list of them
is the Orchestrator's whole contract with the process running it. One record
rather than an argument for each of them: a node names what it needs, and the
graph hands it over.

Which is what makes the walk testable without a database. A test builds its own
record and gets the real nodes, the real state machine and the real routers,
with only the agents and the repositories standing in for themselves. Where a
deployment supplies the real ones is the worker's root,
`apps.worker.assembling`, outside the Orchestrator altogether: it names every
vendor the walk reads.
"""

from __future__ import annotations

from dataclasses import dataclass

from core.events import Publisher
from core.replay import Recorder
from incident_record import EndedByAPerson, StillHeld, WaitForPeople

from orchestrator.walk.ports import (
    ActingFor,
    ActionAlreadyTaken,
    ActionsTaken,
    Admit,
    AdvanceAction,
    ClaimFixFor,
    CompleteAction,
    DiscardTheInterruptedAttempt,
    FetchDependencies,
    FetchDeployments,
    FetchFlagChanges,
    FixClaimedIn,
    Investigate,
    LeadsOf,
    OweAPutBack,
    PlanAction,
    ProposeFix,
    RecallSimilar,
    RecordAction,
    RecordHypothesis,
    RecordOutcome,
    RecordPostmortem,
    RecordSynopsis,
    RecordWeighing,
    RememberIncident,
    Resuming,
    TakeAction,
    TransitionIncident,
    WhatArgusDidIn,
    WritePostmortem,
    WriteSynopsis,
)


@dataclass(frozen=True)
class Collaborators:
    """What the graph hands to its nodes, in one value.

    The agents Argus delegates to, the repositories it writes through, and the
    three the wrapper needs to say where an incident stands and whether anybody
    still wants it. Nothing here is defaulted: a default would be the real
    Anthropic-backed investigator quietly reached by a test that forgot to name
    one, and forgetting is exactly what this record exists to make impossible.
    """

    investigate: Investigate
    record_hypothesis: RecordHypothesis
    fetch_flag_changes: FetchFlagChanges
    fetch_deployments: FetchDeployments
    fetch_dependencies: FetchDependencies
    record_outcome: RecordOutcome
    # The autonomy policy the gate asks. A record field because one of its
    # refusals - a kind nobody declared - cannot be reached with any action
    # Argus has; a stand-in can refuse, and can never admit.
    admit: Admit
    # How often one incident may apply one kind of mitigation to one
    # subject. Configuration rather than a constant, because how many
    # restarts a deployment will tolerate is a deployment's judgement.
    attempts_per_subject: int
    take: TakeAction
    # The change an action will make, worked out by the write tier before the
    # action is claimed, so the claim carries what the write compares with.
    plan_action: PlanAction
    record_action: RecordAction
    complete_action: CompleteAction
    already_taken: ActionAlreadyTaken
    advance_action: AdvanceAction
    # A refuted change recorded as owed back on its claim, before the put-back.
    owe_a_put_back: OweAPutBack
    # What a walk resumed inside the mitigation node reads of the estate and
    # carries on with, picking an earlier worker's attempt up where it stopped.
    resuming: Resuming
    # Which action the changes made inside it are for, so the write tier marks
    # each with it. The process's own `Holding`, which the write client reads.
    acting_for: ActingFor
    propose_fix: ProposeFix
    # The incident's fix claim, read and written: what Code-Fix decided to
    # propose, recorded before any of it is written, so a step run again
    # pushes it rather than asking the model again.
    claimed_fix: FixClaimedIn
    claim_fix: ClaimFixFor
    actions_taken: ActionsTaken
    recall_similar: RecallSimilar
    remember_incident: RememberIncident
    write_postmortem: WritePostmortem
    record_postmortem: RecordPostmortem
    write_synopsis: WriteSynopsis
    record_synopsis: RecordSynopsis
    transition_incident: TransitionIncident
    # What a step run again from its checkpoint takes back of its interrupted
    # attempt before it runs, saying so where there was anything.
    discard_the_interrupted_attempt: DiscardTheInterruptedAttempt
    publisher: Publisher
    recorder: Recorder
    # Whether a person has ended the incident, and how. Asked before and after
    # every node and by the agents between their steps, and the one thing a
    # walk's own state cannot tell it.
    ended_by_a_person: EndedByAPerson
    # Whether the run being walked is still this process's. Asked with the
    # ending by the agents between their steps, so a walk paused past its lease
    # stops at its next turn rather than paying for every turn left.
    still_held: StillHeld
    # Holds the walk off its next step while a person Argus asked to confirm
    # the incident is over has yet to answer (D11). Asked before every node.
    wait_for_people: WaitForPeople
    # What people told the incident in its thread, as leads, and where what
    # the Investigator made of each one is kept. The one input to an incident
    # Argus did not produce, read as the walk goes because a person can write
    # while an agent is working.
    leads_of: LeadsOf
    record_weighing: RecordWeighing
    # What Argus did about the incident, read back for Code-Fix with whether
    # each change still stands - the later word on what the leads were weighed
    # as.
    what_argus_did: WhatArgusDidIn
    # How many times one incident may be investigated. On the record
    # rather than read by the graph, because it is a fact about the
    # deployment and `build_graph` is where a walk is assembled, not
    # where configuration is discovered (V7b).
    max_rounds: int
