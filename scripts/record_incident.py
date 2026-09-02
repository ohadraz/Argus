from __future__ import annotations

import argparse
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx
import psycopg
from anthropic_double.recordings import RECORDINGS_DIR
from argus_core.config import get_settings
from argus_core.timestamps import to_iso

"""Captures a real model answer as a replayable recording.

Recording is a proxy inside the Anthropic double rather than a script that
builds its own request: the double is told to record, then the stack drives one
real incident through it, so the request that gets stored is by construction the
request the adapter sends - prompt, schema transform and all.

This script is the part around that: arm the double, stage the Target Service,
fire the alert, and say what was written. It exists so a recording is one
command rather than four hand-typed curls whose order matters - seeds take
precedence over record mode, so a double that was seeded by a previous run
records nothing and the mistake looks like a working run.

Costs one real investigation, which is why it is a session nobody runs by
accident and never part of a suite.
"""

ARGUS_WEB_BASE_URL = "http://localhost:8000"
TARGET_SERVICE_BASE_URL = "http://localhost:8080"
ANTHROPIC_DOUBLE_BASE_URL = "http://localhost:8091"
DATABASE_URL = get_settings().database_url

A_WHOLE_INVESTIGATION_SECONDS = 900.0


def _an_alert_for(service: str, alert_name: str) -> dict[str, Any]:
    """A Grafana webhook payload, as Grafana would send it.

    `startsAt` is now, and that matters: retrieval is anchored on the alert
    time and the Target Service stages a scenario relative to the moment it was
    staged, so a fixed timestamp would point the window at minutes the fixture
    never wrote.
    """
    summary = f"Error rate above threshold on {service}"

    return {
        "receiver": "argus-webhook",
        "status": "firing",
        "alerts": [
            {
                "status": "firing",
                "labels": {
                    "alertname": alert_name,
                    "service": service,
                    "severity": "critical",
                },
                "annotations": {"summary": summary},
                "startsAt": to_iso(datetime.now(UTC)),
                "endsAt": "0001-01-01T00:00:00Z",
                "generatorURL": f"http://grafana.local/alerting/grafana/{service}/view",
                "fingerprint": "abc123def456",
            }
        ],
        "groupLabels": {"alertname": alert_name},
        "commonLabels": {"alertname": alert_name, "service": service},
        "commonAnnotations": {"summary": summary},
        "externalURL": "http://grafana.local",
        "version": "1",
        "groupKey": f'{{}}/{{alertname="{alert_name}"}}',
    }


def _replay_from(name: str) -> None:
    """Serves a stored recording for every call instead of forwarding upstream.

    The same drive, for free. What it is for is the question a recording cannot
    answer on its own - what the *graph* did with that answer - and being able
    to ask it repeatedly, without paying for a fresh verdict each time, is the
    difference between reading a timeline and guessing at one.
    """
    with httpx.Client(base_url=ANTHROPIC_DOUBLE_BASE_URL, timeout=10.0) as control:
        control.post("/double-control/reset").raise_for_status()
        control.post(
            "/double-control/seed", json={"recording": name, "repeat": None}
        ).raise_for_status()


def _the_timeline_of(incident_id: str) -> list[str]:
    """What the incident recorded about itself, in order.

    Read here rather than left for someone to query afterwards, because the
    stack is torn down the moment this script returns - and the timeline is the
    only account of which branch the walk actually took.
    """
    with psycopg.connect(DATABASE_URL) as connection, connection.cursor() as cursor:
        cursor.execute(
            "SELECT to_status, actor, action, result "
            "  FROM timeline_event "
            " WHERE incident_id = %s "
            "ORDER BY created_at",
            (incident_id,),
        )
        return [
            f"  {status:<14} {actor or '-':<13} {action or '-'}"
            + (f" :: {result}" if result else "")
            for status, actor, action, result in cursor.fetchall()
        ]


def _arm_the_double(name: str) -> None:
    """Clears anything a previous run left queued, then enters record mode.

    The reset is not optional: a seeded answer is served ahead of record mode,
    so a double still holding a seed would replay it and store nothing.
    """
    with httpx.Client(base_url=ANTHROPIC_DOUBLE_BASE_URL, timeout=10.0) as control:
        control.post("/double-control/reset").raise_for_status()
        control.post("/double-control/record", json={"name": name}).raise_for_status()


def _stage(scenario_id: str) -> None:
    httpx.post(
        f"{TARGET_SERVICE_BASE_URL}/scenario/seed",
        json={"scenario_id": scenario_id},
        timeout=30.0,
    ).raise_for_status()


def _drive_one_incident(service: str, alert_name: str) -> str:
    """Fires the alert and waits out the whole investigation.

    The webhook runs the graph in-process and answers only when the incident
    reaches a terminal status, so this call is as long as the walk is - several
    model calls and a verification window per attempt.
    """
    response = httpx.post(
        f"{ARGUS_WEB_BASE_URL}/webhooks/alerts",
        json=_an_alert_for(service, alert_name),
        timeout=A_WHOLE_INVESTIGATION_SECONDS,
    )
    response.raise_for_status()

    return str(response.json().get("incident_id", "unknown"))


def _the_set_named(name: str) -> list[Path]:
    """Every file one recording's answers are stored across, in answer order.

    A recording is not one file: a walk takes as many turns as it takes, and
    each answer is stored beside the last under a numbered name. The digits
    are checked rather than just the prefix, because two recordings can share
    one - `feature-flag-toggle-red-herring` is not the fourth answer of
    `feature-flag-toggle`.
    """
    belonging = [
        path
        for path in RECORDINGS_DIR.glob(f"{name}*.json")
        if path.stem == name or path.stem[len(name) + 1:].isdigit()
    ]

    # By the number rather than by the name: the first answer carries no digits
    # at all, and sorting the rest as text would put a tenth answer second.
    return sorted(belonging, key=lambda path: int(path.stem[len(name) + 1:] or 1))


def _discard_what_was_not_answered_again(name: str, started_at: float) -> list[Path]:
    """Deletes the answers of the previous recording this run did not replace.

    Not housekeeping - correctness. `save` overwrites one file at a time, so a
    walk that ends in two turns leaves the third through eighth answers of the
    walk before it exactly where they were, and the double serves them: the
    replayed investigation reads six answers to questions this recording never
    asked, and escalates on evidence from another incident. The failure is
    silent both ways round, because a longer new recording overwrites the lot
    and looks fine.

    Done after the run rather than before it, and by what the run actually
    wrote. Clearing up front is the same mistake in the other direction: an
    incident that never reaches the model - one escalated on retrieval alone,
    which is a real path and a tested one - records nothing, and a store
    emptied in advance of it loses a recording that no rerun can put back.

    Returns what it deleted, so a run can say so rather than leaving the
    difference between "this walk was shorter" and "your store just lost six
    files" to be noticed later.
    """
    stale = [
        path
        for path in _the_set_named(name)
        if path.stat().st_mtime < started_at
    ]
    for path in stale:
        path.unlink()

    return stale


def main() -> int:
    # The timeline printed at the end quotes the model, and the model writes
    # arrows and dashes this console cannot encode - a Windows terminal defaults
    # to a legacy codepage, and printing one character outside it raises. That
    # ended a *paid* run in a traceback after the recordings were safely on
    # disk, which reads as a failed recording and invites running it again.
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("name", help="what to store the recording as")
    parser.add_argument(
        "scenario",
        nargs="?",
        help="the Target Service scenario to stage first; omit to stage nothing, "
             "which is how the absence-of-evidence recording is captured",
    )
    parser.add_argument("--service", default="io-shop")
    parser.add_argument("--alert-name", default="HighErrorRate")
    parser.add_argument(
        "--replay",
        action="store_true",
        help="serve the stored recording instead of calling the real API",
    )
    arguments = parser.parse_args()

    if arguments.replay:
        _replay_from(arguments.name)
    else:
        _arm_the_double(arguments.name)

    # Read before anything is written, and from the clock the files are stamped
    # by: what makes an answer stale is that this run did not write it, and
    # every comparison after this point is against this moment.
    started_at = time.time()

    if arguments.scenario:
        _stage(arguments.scenario)

    incident_id = _drive_one_incident(arguments.service, arguments.alert_name)

    print(f"incident [{incident_id}] drove scenario [{arguments.scenario or 'none'}]")

    if not arguments.replay:
        discarded = _discard_what_was_not_answered_again(arguments.name, started_at)
        written = [path.stem for path in _the_set_named(arguments.name)]
        print(f"recorded: {', '.join(written) or 'nothing'}")
        if discarded:
            print(
                f"discarded: {', '.join(path.stem for path in discarded)} "
                f"- answers of a longer walk this run did not need"
            )

    print("timeline:")
    for entry in _the_timeline_of(incident_id):
        print(entry)

    return 0


if __name__ == "__main__":
    sys.exit(main())
