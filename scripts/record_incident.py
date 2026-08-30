from __future__ import annotations

import argparse
import sys
from datetime import UTC, datetime
from typing import Any

import httpx
import psycopg
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


def _recorded_names(name: str) -> list[str]:
    with httpx.Client(base_url=ANTHROPIC_DOUBLE_BASE_URL, timeout=10.0) as control:
        available = control.get("/double-control/state").json()

    return [
        recording
        for recording in available.get("available_recordings", [])
        if recording == name or recording.startswith(f"{name}-")
    ]


def main() -> int:
    # The timeline printed at the end quotes the model, and the model writes
    # arrows and dashes this console cannot encode - a Windows terminal defaults
    # to a legacy codepage, and printing one character outside it raises. That
    # ended a *paid* run in a traceback after the recordings were safely on
    # disk, which reads as a failed recording and invites running it again.
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("name", help="what to store the recording as")
    parser.add_argument("scenario", help="the Target Service scenario to stage first")
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

    _stage(arguments.scenario)
    incident_id = _drive_one_incident(arguments.service, arguments.alert_name)

    print(f"incident [{incident_id}] drove scenario [{arguments.scenario}]")

    if not arguments.replay:
        print(f"recorded: {', '.join(_recorded_names(arguments.name)) or 'nothing'}")

    print("timeline:")
    for entry in _the_timeline_of(incident_id):
        print(entry)

    return 0


if __name__ == "__main__":
    sys.exit(main())
