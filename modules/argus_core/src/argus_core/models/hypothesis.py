from __future__ import annotations

from pydantic import BaseModel, Field, model_validator

from argus_core.ids import UuidStr, new_id
from argus_core.models.cause import CauseType


class Hypothesis(BaseModel):
    """What the Investigator concluded, and what it concluded it from.

    One model, not two. A row in the `hypothesis` table (spec §11.1) is a
    hypothesis written down, not a separate concept - so the repository stores
    and loads this, rather than declaring a parallel shape of its own. It
    crosses agent boundaries as well: the Investigator forms it, Mitigation
    answers it with confirmed/refuted (§7.3), Postmortem quotes it.

    `id` is generated here rather than by the database, because an entity has
    identity by definition - see `argus_core.ids.new_id`. `created_at` is
    deliberately absent: it is an audit fact the table records, and nothing in
    the domain reads it.

    `cause_type` is `None` when the evidence did not identify a cause, and
    `confidence` is `None` with it. The two travel together deliberately: see
    the validator below.

    `subject` is the specific thing the cause names - for a feature-flag
    toggle, the flag. It is a field rather than a sentence in `summary` because
    Mitigation acts on it: a conclusion that survives only as prose forces every
    consumer to either parse English or investigate the incident again, and two
    phases investigating separately can reach different answers, of which the
    acting one is not the reasoning one.

    A plain string, and named for no particular cause, because a `Hypothesis` is
    shared by every cause type: a field called `flag` would be dead weight on a
    bad deployment and a lie on whatever comes next. What the string means is
    already fixed by `cause_type` beside it.
    """

    id: UuidStr = Field(default_factory=new_id)
    incident_id: UuidStr
    summary: str
    cause_type: CauseType | None
    # A probability, so it lives on the scale probabilities live on. Declared
    # here because it is the only place it can be: the answer tool's schema
    # cannot carry `minimum` and `maximum` - a strict tool schema rejects
    # bounds on a number - so a model writing 1.4 is refused on the way into
    # the domain rather than on the way out of the API.
    confidence: float | None = Field(ge=0.0, le=1.0)
    supporting_evidence: list[str]
    subject: str | None = None
    # Where this hypothesis came in the investigation's own ordering, best
    # first. Data rather than list position, because rows come back from a
    # table in no order at all, and an ordering that lived only in a list would
    # not survive being written down. Defaults to 1: an investigation that named
    # one explanation named the best one.
    rank: int = 1
    tested: bool = False
    result: str | None = None

    @model_validator(mode="after")
    def _a_cause_and_a_confidence_come_together(self) -> Hypothesis:
        """Rejects a confident verdict that names nothing.

        "I found no cause, and I am 90% sure" is a contradiction, and it is
        the exact shape of the bug that `STUB_CONFIDENCE` used to produce: an
        answer that read confident while identifying nothing, which a human
        picking up the incident could not tell from a real diagnosis.

        Enforced here rather than corrected at the point of construction,
        because a correction is a rule every future code path has to remember,
        and nothing makes it.
        """
        if (self.cause_type is None) != (self.confidence is None):
            raise ValueError(
                "a hypothesis has both a cause and a confidence, or neither - "
                f"got cause_type={self.cause_type!r}, confidence={self.confidence!r}"
            )

        return self

    @model_validator(mode="after")
    def _a_subject_is_something_a_cause_names(self) -> Hypothesis:
        """Rejects a subject with nothing to blame it for.

        "I blame `monthly-spend-feature`, for nothing" is the same incoherence
        the rule above refuses, one field over - and a worse one to let past,
        because Mitigation reads the subject to decide what to change. An
        undetermined verdict that still named something would arrive as a flag
        to act on with no diagnosis behind it.

        The reverse is legitimate and deliberately allowed: a cause can name no
        subject, because not every cause has one this system can identify.
        """
        if self.subject is not None and self.cause_type is None:
            raise ValueError(
                "a hypothesis names a subject only for a cause it identified - "
                f"got subject={self.subject!r} with cause_type=None"
            )

        return self

    def is_actionable(self) -> bool:
        """Whether there is anything here to act on at all.

        The one gate a reversible mitigation needs. Confidence is not the
        question: an action that is taken one at a time, confirmed against the
        service, and put back when it does not help costs a couple of minutes
        and nothing else, so what matters is whether a cause was named - not how
        sure the model was that it was the right one. Being wrong about a
        correlated change is the ordinary case, and the walk is what answers it.

        Confidence still decides *order*, and still gates everything a human has
        to approve or be woken for - see `is_confident_enough`.
        """
        return self.cause_type is not None

    def is_confident_enough(self, threshold: float) -> bool:
        """Whether this hypothesis is confident enough to put in front of a
        human - a pull request, a rollback, a page (spec §10, §13).

        Not what admits a reversible mitigation: that one asks only whether a
        cause was named. This asks the question confidence is actually good for,
        which is whether something irreversible or somebody's attention is
        warranted.

        An undetermined hypothesis never is. That is the honest answer - there
        is no cause to act on - rather than a low score standing in for one.

        The threshold is a parameter rather than read from `Settings`: a
        hypothesis is a domain object and has no business knowing how Argus is
        configured. Callers that need the configured value already hold it.
        """
        return self.confidence is not None and self.confidence >= threshold
