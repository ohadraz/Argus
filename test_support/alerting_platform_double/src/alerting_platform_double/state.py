"""What an alerting platform holds before anybody asks it anything.

The seed both adapters in the port's suite are built from: the double reads it
directly, and the suite's Grafana stand-in serves it in Grafana's own shapes.
Every value is frozen and every collection a tuple, so a seed is the same seed
whoever holds it and however many platforms are built from it.
"""

from __future__ import annotations

from dataclasses import dataclass

from alerting_platform import RuleEvaluation


@dataclass(frozen=True)
class HeldRule:
    """One rule the platform evaluates: its last evaluation as the platform
    keeps it, and whether that evaluation measured anything.

    `measured` is False for an evaluation whose query failed or found no data -
    one the platform still reports a state for, and which says nothing about
    the service. The rule's definition is read all the same, so its series is
    still there to be followed.

    `evaluation.series_unit` is the unit the rule's panel shows its values in,
    and may be held for a rule with no series: the platform shows a unit for a
    panel whatever the rule's shape, and the port answers one only beside the
    series it is the unit of.
    """

    evaluation: RuleEvaluation
    measured: bool = True


@dataclass(frozen=True)
class AlertingState:
    """Every rule the platform evaluates."""

    rules: tuple[HeldRule, ...]
