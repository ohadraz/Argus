"""The door a node writes the incident record through, and only a node.

Not the module's only door to it, and not meant to be. A walk being started, a
withdrawal undoing what a walk did, and a finished incident being read back for
its postmortem all reach `argus_incidents.repository` directly - none of them
happens inside a node, and each says at its own site why it reads what it does.
Two more siblings reach the repositories for things that are not the incident
record at all: the run queue and the exchange-rate cache. One write here is not
the incident record either - what the incident tried, filed for long-term
memory - and it is here because a node makes it.

So the line this draws is the one a graph cares about. A node is handed its
collaborators and has to be assertable with no database behind it; the process
around the graph is where a database is a fact of life.
"""

from __future__ import annotations

from datetime import datetime

from agent_postmortem import said_off_the_page
from argus_core import Connections
from argus_core.events import (
    ExecutiveSynopsisWithheld,
    ExecutiveSynopsisWritten,
    IncidentEvent,
    LeadWeighed,
    PostmortemWritten,
)
from argus_core.models import (
    ActionProgress,
    ActionType,
    ExecutiveSynopsisDocument,
    Hypothesis,
    IncidentStatus,
    PostmortemDocument,
    TakenAction,
    ThreadMessage,
    UndoDescriptor,
    Undone,
    Verdict,
    WhatArgusDid,
    the_identity_recorded,
)
from argus_incidents import PublisherFor, publish_beside
from argus_incidents.repository import (
    conversation,
    hypotheses,
    incidents,
    postmortems,
    synopses,
    taken_actions,
)
from incident_memory import filing
from incident_memory.composing import VERDICTS_THAT_JUDGE_AN_ACTION
from incident_memory.records import RememberedIncident

from orchestrator.gathering import what_became_of
from orchestrator.walk.ports import ClaimedAction


class Records:
    """Every write a node makes, against one source of connections.

    One object rather than nine functions taking a tenth argument: each of its
    methods is already the shape of the `Protocol` a node asks for, so a bound
    method goes straight in where the node expects a collaborator and the
    database stops appearing in any node's signature.

    Built once where the graph is assembled, from whatever that process holds -
    a pool while Argus is running, a single connection in a script.

    A connection per method, which is what lets a node ask one question without
    holding anything open between them - and also why `gather_evidence` is not
    here. Its six reads of one incident are one answer, taken on one connection
    so that they describe the same moment; through this object they would be
    six connections and six moments, which is a worse account of an incident
    for the sake of one idiom.
    """

    def __init__(self,
                 connections: Connections,
                 publisher_for: PublisherFor) -> None:
        self._connections = connections
        self._publisher_for = publisher_for

    def hypothesis(self, hypothesis: Hypothesis, /) -> None:
        with self._connections() as conn:
            hypotheses.record(conn, hypothesis)

    def outcome(self, hypothesis_id: str, tested: bool, result: str) -> None:
        with self._connections() as conn:
            hypotheses.record_outcome(conn, hypothesis_id, tested=tested, result=result)

    def transition(
        self,
        incident_id: str,
        to_status: IncidentStatus,
        narrating: IncidentEvent
    ) -> bool:
        """Moves the incident, and says so, in one write - and answers whether
        it moved.

        `narrating` is required rather than optional because there is no such
        thing as a transition nobody accounts for: the account is what the
        incident is read from, and a status that arrived without a sentence
        about it is a row a human cannot act on.

        The status is the whole of the write. What moved it, why, and how sure
        it was live in the event rather than in columns beside the status -
        there is one account of an incident now, and a second one shaped like a
        table is how the two came to disagree.

        One connection for both, so the two commit together - and the account
        written last, inside a savepoint of its own, so it can fail without
        taking the transition with it.

        A move the row refused is not said either. An incident a person withdrew
        while the node was running stays withdrawn, and a line announcing the
        status the node would have written is the account contradicting the
        row it accounts for.
        """
        with self._connections() as conn:
            moved = incidents.transition(conn, incident_id, to_status, at=narrating.at)

            if moved:
                publish_beside(conn, narrating, self._publisher_for(conn))

        return moved

    def claim_action(
        self,
        incident_id: str,
        hypothesis_id: str,
        action_type: ActionType,
        subject: str | None,
        at: datetime
    ) -> bool:
        with self._connections() as conn:
            return taken_actions.claim(
                conn,
                incident_id,
                hypothesis_id=hypothesis_id,
                action_type=action_type,
                subject=subject,
                at=at
            )

    def complete_action(
        self,
        incident_id: str,
        hypothesis_id: str,
        outcome: Verdict,
        undo_descriptor: UndoDescriptor | None,
        narrating: IncidentEvent,
        performed: bool = True,
        *,
        left_behind_known: bool,
        undone: Undone | None = None
    ) -> None:
        """Records what came of the action, and says so, in one write.

        The same pairing a transition gets, for the same reason and in the same
        order: the verdict is written first and the sentence about it second,
        inside a savepoint. Published separately - and it used to be published
        *first* - a walk that stopped in between announced a verdict that was
        never recorded against the action it was about.
        """
        with self._connections() as conn:
            taken_actions.complete(
                conn,
                incident_id,
                hypothesis_id=hypothesis_id,
                outcome=outcome,
                undo_descriptor=undo_descriptor,
                performed=performed,
                left_behind_known=left_behind_known,
                undone=undone
            )
            publish_beside(conn, narrating, self._publisher_for(conn))

    def advance_action(
        self,
        incident_id: str,
        hypothesis_id: str,
        to: ActionProgress,
        undo_descriptor: UndoDescriptor | None
    ) -> None:
        """Moves a claimed action on, and says nothing about it.

        Nothing said, unlike a completion: the change being made is announced
        before it is taken, and a resumed walk's answer is narrated by the walk
        that reached it. This is the row catching up.
        """
        with self._connections() as conn:
            taken_actions.advance(
                conn,
                incident_id,
                hypothesis_id=hypothesis_id,
                to=to,
                undo_descriptor=undo_descriptor
            )

    def claimed_action(self,
                       incident_id: str,
                       hypothesis_id: str) -> ClaimedAction | None:
        """What an earlier attempt on this candidate staked, and what came of it.

        One read, because it is one row. Asked for the verdict and the moment
        separately it was fetched twice to take one column each - and the two
        answers could come from either side of a write that landed between them.

        The outcome is passed on as it was read. It arrives as a value already
        - the row is parsed where the column is read, which is the one place
        that decides what an outcome Argus cannot spell is - so converting it
        again here would be this adapter holding an opinion about a policy it
        does not own, and the two conversions this replaced disagreed about
        exactly that.
        """
        with self._connections() as conn:
            taken_action = taken_actions.get_action_for_hypothesis(
                conn, incident_id, hypothesis_id)

        if taken_action is None:
            return None

        return ClaimedAction(
            outcome=taken_action.outcome,
            claimed_at=taken_action.taken_at,
            progress=taken_action.progress
        )

    def postmortem(self, incident_id: str, document: PostmortemDocument, /) -> None:
        """Stores the write-up, and says that there is one, in one write.

        The account needs the event for the reason every other step here does:
        nothing in the walk tells anybody anything, so a postmortem nobody
        published is a postmortem only somebody already looking at the page
        would ever find.

        The summary travels on the event rather than being read back from the
        row, so that a destination says what the document said at the moment
        it was written - as it is said off the page, since a destination has
        none of the rows its labels lead to - and beside the row, inside a savepoint, so a
        subscriber having a bad day cannot lose the document itself. The row
        is stamped with the event's moment, so the page's author line and the
        account's line are one instant.
        """
        summary = document.executive_summary
        written = PostmortemWritten(
            incident_id=incident_id,
            cause_in_plain_words=document.cause_in_plain_words,
            executive_summary=said_off_the_page(summary) if summary is not None else None,
            engineer_minutes=document.engineer_minutes
        )

        with self._connections() as conn:
            postmortems.record(conn, incident_id, document, at=written.at)
            publish_beside(conn, written, self._publisher_for(conn))

    def synopsis(self, incident_id: str, synopsis: ExecutiveSynopsisDocument, /) -> None:
        """Stores the executive synopsis, and says that there is one - or that
        it was given up, and why - in one write.

        Said with no word of it, unlike the postmortem: the synopsis shows pay,
        and the account is read by everyone. Whoever sends it reads the row.
        """
        said: ExecutiveSynopsisWritten | ExecutiveSynopsisWithheld = (
            ExecutiveSynopsisWritten(incident_id=incident_id) if synopsis.overview is not None
            else ExecutiveSynopsisWithheld(incident_id=incident_id,
                                           reason=synopsis.withheld_because or ""))

        with self._connections() as conn:
            synopses.record(conn, incident_id, synopsis, at=said.at)
            publish_beside(conn, said, self._publisher_for(conn))

    def memory(self, record: RememberedIncident, /) -> None:
        """Files what this incident tried, for long-term memory to be given.

        A row rather than the store itself, and here beside the incident's own
        rows for the reason they are here: it is a node's write, made on a
        connection the fence refuses for a run another claim holds. The store
        is filled from these rows by a process of its own.
        """
        with self._connections() as conn:
            filing.file(conn, record)

    def weighing(self, lead: ThreadMessage, /) -> None:
        """Keeps what the Investigator made of a lead, then says so.

        Not one write, unlike the pairs above. The standing is committed on its
        own, as every write to a person's message is, and the line is written
        after it inside a savepoint - so a sentence nobody could write costs
        the timeline a line, and never the standing the next round, Code-Fix
        and the postmortem read.

        A lead carrying no weighing is refused rather than skipped: the
        findings hand back only leads they weighed, and one without is a
        caller saying something was concluded when nothing was.
        """
        if lead.weighing is None:
            raise ValueError(f"lead {lead.message} carries no weighing to keep")

        with self._connections() as conn:
            conversation.weighed(conn, lead.message, lead.weighing)
            publish_beside(conn, LeadWeighed(
                incident_id=lead.incident_id,
                message=lead.message,
                standing=lead.weighing.standing,
                reason=lead.weighing.reason
            ), self._publisher_for(conn))

    def leads(self, incident_id: str, /) -> list[ThreadMessage]:
        """What people told this incident in its thread, as leads, with what an
        investigation last made of each.

        Here beside the weighing for `actions_taken`'s reason: it is the rows
        the weighing writes to, read back, and a second object holding one
        query against them would be a second place that knows where a lead
        lives.
        """
        with self._connections() as conn:
            return conversation.get_leads_by_incident(conn, incident_id)

    def actions_taken(self, incident_id: str, /) -> list[TakenAction]:
        """Every action stored against this incident, with what each reached.

        A read among writes, as `leads` is. It belongs beside them
        because it is the same table the claim and the completion above wrote
        to, read back once the incident is over - and a second object holding
        one query against one of these tables would be a second place that
        knows where an action lives.
        """
        with self._connections() as conn:
            return taken_actions.get_by_incident(conn, incident_id)

    def what_argus_did(self, incident_id: str, /) -> list[WhatArgusDid]:
        """Every action this incident judged, in the order taken, with its
        verdict and whether its change still stands.

        Off the rows rather than the walk's state, because the row is what
        says whether a change was put back - and in the write-up's words for
        it, so Code-Fix and the write-up say one action one way.

        Kept as memory keeps them: an action that reached no verdict says
        nothing about the cause, and one on no subject, or of a kind this
        version cannot name, is not an action anybody can be told of.
        """
        return [
            WhatArgusDid(identity=identity, verdict=taken.outcome, standing=what_became_of(taken))
            for taken in self.actions_taken(incident_id)
            if isinstance(taken.outcome, Verdict)
            and taken.outcome in VERDICTS_THAT_JUDGE_AN_ACTION
            and taken.subject
            and (identity := the_identity_recorded(taken.type, taken.subject)) is not None
        ]
