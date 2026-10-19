"""How it was found: when it began, when the alert fired, how long that took,
and how long the rule waits before it fires.

No gap where no onset was recorded: an alert time alone measures nothing.
"""

from __future__ import annotations

from datetime import timedelta

from argus_core.models import Alert, Detection, PostmortemDocument
from pydantic import BaseModel, ConfigDict

from postmortem_rendering.formatting import as_span
from postmortem_rendering.lines import Line, Role, Run
from postmortem_rendering.supporting import EvidenceRow


class DetectionSection(BaseModel):
    """The sentence, or the one said in its place where detection was not
    recorded - and what the alert said, a row under the label the prose cites
    it by, `None` where its sender said nothing of its own."""

    model_config = ConfigDict(frozen=True)

    line: Line | None
    absent: str | None
    said_heading: str = "What the alert said"
    said: EvidenceRow | None = None


def the_detection(postmortem: PostmortemDocument, alert: Alert) -> DetectionSection:
    """Detection said as one sentence: the onset where there is one, then the
    alert and how long after it fired."""
    detection = postmortem.detection
    if detection is None:
        return DetectionSection(line=None, absent="How it was detected was not recorded.")

    if detection.onset_at:
        runs = [Run(text="The incident on "),
                Run(text=alert.service, role=Role.CODE),
                Run(text=" began at "),
                Run.a_moment(detection.onset_at),
                Run(text=f". {alert.alert_name} fired at ")]
    else:
        runs = [Run(text=f"The onset is unknown. {alert.alert_name} fired at ")]

    runs.append(Run.a_moment(detection.alerted_at))

    if detection.gap is not None and detection.gap >= timedelta(0):
        gap = f", {as_span(detection.gap)} later"
    elif detection.gap is not None:
        # The sender dates the alert and Argus measures the onset, and the two
        # can cross: a rule with no wait fires on the first minute that departs.
        gap = f", {as_span(-detection.gap)} before the measured onset"
    else:
        gap = ""

    if said_after := gap + _the_rules_wait(detection):
        runs.append(Run(text=said_after))

    runs.append(Run(text="."))

    said = detection.said
    return DetectionSection(line=Line(runs=tuple(runs)), absent=None,
                            said=(EvidenceRow(label=said.label,
                                              said=Line(runs=(Run(text=said.text),)))
                                  if said is not None else None))


def _the_rules_wait(detection: Detection) -> str:
    """How long the rule's condition must hold before it fires, said beside the
    gap and never inside it - and nothing where no rule paged.

    A rule fires only once its condition has held for its wait, so an alert
    fewer minutes after the onset than that says the condition held before the
    measured onset: a finding the record makes, said rather than left for a
    reader to notice. Only where the alert came after the onset; one dated
    before it says so already. A wait nobody could read is not one of nothing.
    """
    waits = detection.rule_waits

    if detection.rule_wait_unread:
        return " - how long its rule waits before firing could not be read"

    if waits is None:
        return ""

    if not waits:
        return " - its rule fires as soon as its condition holds"

    if detection.gap is not None and timedelta(0) <= detection.gap < waits:
        return (f" - shorter than the {as_span(waits)} its rule's condition must hold "
                f"before it fires, so the condition held before the measured onset")

    return f" - its rule fires only once its condition has held for {as_span(waits)}"
