from __future__ import annotations

from enum import StrEnum
from typing import assert_never

from argus_core.events import (
    ActionTaken,
    AgentInvoked,
    AlertAcknowledged,
    AwaitingRecovery,
    ChangesRetrieved,
    ChannelsUnread,
    CommunicationFailed,
    FlagChangesRetrieved,
    HypothesisFormed,
    IncidentEvent,
    LogsRetrieved,
    MetricsRetrieved,
    OnsetDetected,
    PostmortemWritten,
    RecoveryChecked,
    RetrievalRequested,
    StatusChanged,
    VerdictReached,
)

"""Which of the things Argus publishes a human hears, and how loudly.

Everything is published and everything is on the dashboard; a channel is not a
dashboard. What earns an interruption is what Argus found, what it changed,
what it concluded and where the incident now stands - not the reading it did to
get there, which is evidence somebody goes looking for rather than news.

Here rather than where events are published. A component that knew which of its
own lines were worth interrupting a person with would be making an editorial
decision in the middle of doing its job - and the decision would then be made
once per publisher, differently each time.
"""


class Register(StrEnum):
    """How loudly a line is said, if it is said at all.

    Said in words a destination can translate rather than in any destination's
    own: Slack reads these as a channel message and a thread reply, email as a
    send and a digest. A register named `thread` would put Slack's furniture in
    the one module that is supposed to outlast the choice of destination.
    """

    UNSAID = "unsaid"
    # Heard by whoever chose to follow this incident. The body of the story,
    # and the reason following is a choice made once rather than an
    # interruption taken repeatedly.
    FOLLOWED = "followed"
    # Addressed to everyone, including whoever is not watching: how an incident
    # opened, and how it ended.
    ANNOUNCED = "announced"
    # Kept rather than said: the write-up an incident leaves behind, which
    # belongs where write-ups are looked for rather than in the conversation
    # about an incident that is already over. Slack reads this as the
    # postmortem channel, email as an attachment.
    FILED = "filed"


def how_it_is_said(event: IncidentEvent) -> Register:
    """The register one published event is said in, or that it is not said.

    A `match` over the event types rather than a lookup keyed on `kind`, for
    the reason the narration does it: an event type nobody has decided about is
    then a type error rather than a line that quietly goes nowhere - and going
    nowhere is the failure that would never be noticed.
    """
    match event:
        case AlertAcknowledged():
            # The one line nobody can have chosen to follow yet, because it is
            # what there is to follow.
            return Register.ANNOUNCED
        case StatusChanged():
            # Terminal rather than named: `fixing` reads like an ending and is
            # not one, and the state machine already knows the difference.
            return (Register.ANNOUNCED if event.to_status.is_terminal()
                    else Register.FOLLOWED)
        case OnsetDetected() | HypothesisFormed() | ActionTaken() | VerdictReached():
            return Register.FOLLOWED
        case AwaitingRecovery():
            # Said, unlike the looks that follow it: this is the longest
            # silence in an incident, and a conversation that went quiet for
            # six minutes without saying it was waiting reads as one that
            # stopped.
            return Register.FOLLOWED
        case PostmortemWritten():
            # The one line that is not about the incident being worked but
            # about the record it leaves. Filed rather than announced, so that
            # a team keeping its write-ups somewhere of their own gets them
            # there - and a team that does not has said so by leaving the
            # channel unset, and gets them in the war room.
            return Register.FILED
        case CommunicationFailed():
            # Written because a destination refused a line, and never sent
            # anywhere itself. Telling Slack that Slack could not be told is
            # either impossible or noise, and a relay that tried would make a
            # new failure out of every failure. The page is where this is read.
            return Register.UNSAID
        case (AgentInvoked() | RetrievalRequested() | MetricsRetrieved()
              | LogsRetrieved() | ChangesRetrieved() | FlagChangesRetrieved()
              | ChannelsUnread() | RecoveryChecked()):
            # Everything that reports a look rather than a finding. Forty log
            # lines read is a fact about the investigation's method, and a
            # channel reporting it would bury the four lines that matter.
            # `agent-invoked` is here for the same reason: which of Argus's
            # agents is working is a fact about how Argus is built.
            return Register.UNSAID
        case _:
            assert_never(event)
