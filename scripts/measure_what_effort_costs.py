"""What one investigation spends at each effort, measured rather than assumed.

The eval answers whether the model is still right at a lower effort. It cannot
answer what the lower effort buys, because it records outcomes and not tokens -
so this runs the same pinned incidents at two efforts and counts what each one
billed.

All four counts, the way `Budget` charges them: with caching on, `input_tokens`
is only the uncached remainder, and a comparison that read it alone would
credit an effort for tokens that merely moved into the cache.

One run per incident per effort. Token counts vary far less between runs than
outcomes do - what is being compared is the size of a conversation, not whether
a judgement landed - so a handful of incidents at one run each says more per
dollar than one incident at ten.

Spends real money on every run: six incidents at each effort named.
"""

from __future__ import annotations

import sys
from collections import Counter
from collections.abc import Callable
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from agent_investigator import investigate  # noqa: E402
from agent_investigator.budget import Budget, InvestigationSettings  # noqa: E402
from argus_core import get_settings, new_id  # noqa: E402
from argus_core.llm import build_llm_client  # noqa: E402
from argus_core.models import (  # noqa: E402
    ChangeEvent,
    Effort,
    MetricBucket,
    ToolDefinition,
    Transcript,
    Turn,
)

from tests.eval.test_investigator_eval import (  # noqa: E402
    Incident,
    an_incident_underway_before_the_window_opens,
    an_incident_where_a_deploy_slowed_the_service,
    an_incident_where_a_flag_was_toggled_on,
    an_incident_where_an_upstream_dependency_failed,
    an_incident_with_an_unrelated_change,
    an_incident_with_no_change_event,
)
from tests.framework.investigating import the_configured_thresholds  # noqa: E402
from tests.framework.measuring import the_measurement_of  # noqa: E402

# The file these rows go to, named for the question rather than the run.
WHAT_THIS_MEASURES = "what_an_investigation_bills"

THE_INCIDENTS: dict[str, Callable[[], Incident]] = {
    "flag-toggled-on": an_incident_where_a_flag_was_toggled_on,
    "no-change-event": an_incident_with_no_change_event,
    "upstream-dependency": an_incident_where_an_upstream_dependency_failed,
    "unrelated-change": an_incident_with_an_unrelated_change,
    "deploy-before-latency": an_incident_where_a_deploy_slowed_the_service,
    "lower-bound-onset": an_incident_underway_before_the_window_opens
}

# Each arm is one deployment's worth of choices: which model answers, and how
# hard it is asked to think. Named as pairs rather than swept as a product,
# because what is being compared is a handful of deliberate configurations and
# not every combination of them - and every cell of a product is a bill.
THE_ARMS: tuple[tuple[str, Effort], ...] = (
    ("claude-opus-5", "high"),
    ("claude-opus-5", "medium"),
    ("claude-sonnet-5", "high")
)


def _the_metrics_of(incident: Incident) -> Callable[[str | None], list[MetricBucket]]:
    """The whole span, whatever it is anchored on - as the real channel serves it."""
    def fetch(_: str | None) -> list[MetricBucket]:
        return list(incident.buckets)

    return fetch


def _the_logs_of(incident: Incident) -> Callable[[str, str], list[str]]:
    """Every line the window covers, read off each line's own timestamp prefix.

    No service argument, unlike the other two: the log channel is already asked
    about one service and does not repeat itself.
    """
    def fetch(window_start: str, window_end: str) -> list[str]:
        return [
            line for line in incident.log_lines
            if window_start <= line.split(" ", 1)[0] <= window_end
        ]

    return fetch


def _the_changes_of(incident: Incident) -> Callable[[str, str, str], list[ChangeEvent]]:
    """Every change the window covers, for whichever service is asked about."""
    def fetch(_: str, window_start: str, window_end: str) -> list[ChangeEvent]:
        return [
            change for change in incident.changes
            if window_start <= change.occurred_at <= window_end
        ]

    return fetch


def _what_one_investigation_spent(incident: Incident,
                                  model: str,
                                  effort: Effort) -> Counter[str]:
    """Runs one investigation and returns what it billed, by kind of token."""
    settings = InvestigationSettings.of(get_settings()).model_copy(
        update={"investigation_model": model, "investigation_effort": effort}
    )
    spend = Budget(
        max_tool_calls=settings.investigation_max_tool_calls,
        max_tokens=settings.investigation_max_tokens,
        max_seconds=settings.investigation_max_seconds
    )
    billed: Counter[str] = Counter()
    client = build_llm_client()

    def speak(transcript: Transcript, tools: list[ToolDefinition]) -> Turn:
        turn = client.converse(transcript, tools)
        billed.update({
            "input": turn.input_tokens,
            "output": turn.output_tokens,
            "cache_read": turn.cache_read_tokens,
            "cache_write": turn.cache_write_tokens,
            "turns": 1
        })

        return turn

    investigate(
        incident.alert,
        new_id(),
        fetch_metrics=_the_metrics_of(incident),
        fetch_logs=_the_logs_of(incident),
        fetch_change_events=_the_changes_of(incident),
        settings=settings,
        thresholds=the_configured_thresholds(),
        converse=speak,
        budget=spend
    )

    return billed


def main() -> None:
    """Runs every incident under every arm and records what each one billed.

    One row per incident per arm rather than one per arm: the totals are a sum
    away, and an arm that is dearer on one incident and cheaper on five is a
    thing a total hides. Recorded rather than printed, so the next comparison is
    a diff against this run instead of somebody's memory of it.
    """
    rows: list[dict[str, object]] = []

    for model, effort in THE_ARMS:
        totals: Counter[str] = Counter()

        for name, build in THE_INCIDENTS.items():
            billed = _what_one_investigation_spent(build(), model, effort)
            totals.update(billed)
            rows.append({
                "model": model,
                "effort": effort,
                "incident": name,
                "turns": billed["turns"],
                "input": billed["input"],
                "output": billed["output"],
                "cache_read": billed["cache_read"],
                "cache_write": billed["cache_write"]
            })
            print(
                f"{model}/{effort}  {name:<22} "
                f"turns {billed['turns']:>3}  in {billed['input']:>7}  "
                f"out {billed['output']:>6}  read {billed['cache_read']:>8}  "
                f"write {billed['cache_write']:>7}"
            )

        charged = (
            totals["input"] + totals["output"]
            + totals["cache_read"] + totals["cache_write"]
        )
        print(
            f"{model}/{effort}  {'TOTAL':<22} turns {totals['turns']:>3}  "
            f"in {totals['input']:>7}  out {totals['output']:>6}  "
            f"read {totals['cache_read']:>8}  write {totals['cache_write']:>7}  "
            f"four-count {charged}\n"
        )

    print(f"recorded to {the_measurement_of(WHAT_THIS_MEASURES, rows)}")


if __name__ == "__main__":
    main()
