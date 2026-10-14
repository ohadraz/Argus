"""How it was found: when it began, when the alert fired, and how long that took.

No gap where no onset was recorded: an alert time alone measures nothing.
"""

from __future__ import annotations

from argus_core.models import Alert, PostmortemDocument
from pydantic import BaseModel, ConfigDict

from postmortem_rendering.formatting import as_span
from postmortem_rendering.lines import Line, Role, Run


class DetectionSection(BaseModel):
    """The sentence, or the one said in its place where detection was not
    recorded."""

    model_config = ConfigDict(frozen=True)

    line: Line | None
    absent: str | None


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

    if detection.gap is not None:
        runs.append(Run(text=f", {as_span(detection.gap)} later"))

    runs.append(Run(text="."))

    return DetectionSection(line=Line(runs=tuple(runs)), absent=None)
