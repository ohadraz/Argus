"""The double itself: an HTTPS server that speaks the part of PagerDuty's REST API Argus reads.

Two surfaces, the arrangement every other double here has:

- `GET /incidents/...` and `GET /users/{id}` - what `oncall_source`'s adapter
  talks to, through PagerDuty's own SDK. Five reads, which is exactly the five
  Argus makes: an incident, the incidents carrying a key, an incident's alerts,
  its notes, and the person who acknowledged it.
- `/double-control/*` - what the *test* talks to, to stage an incident and to
  put the double back.

Selecting the double is one setting (`PAGERDUTY_BASE_URL`), which is the point:
nothing in `oncall_source` knows this file exists. Each answer is wrapped the
way PagerDuty wraps it - a single resource under its own name, a list under its
plural with the paging fields beside it - because the SDK unwraps by that name,
and a double answering bare objects would be read as malformed by the very code
it exists to exercise.

Read-only. Argus never writes to PagerDuty, and a double that accepted writes
would be an invitation to start.
"""

from __future__ import annotations

import os
from datetime import UTC, datetime
from typing import Any, Final

from fastapi import FastAPI
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

# Where the double listens. Not an `argus_core` setting, for the reason the
# other doubles' ports are not: the double is not part of Argus, and Argus's own
# config should not grow a field describing a test fixture. HTTPS, because the
# SDK will not address anything else - see `certificate`.
DEFAULT_PORT: Final = int(os.environ.get("PAGERDUTY_DOUBLE_PORT", "8097"))
DEFAULT_BASE_URL: Final = f"https://localhost:{DEFAULT_PORT}"

# PagerDuty's own vocabulary, named here because this is the module that writes
# it. The envelopes first - what the SDK unwraps by - then the fields inside.
_INCIDENT_ENVELOPE: Final = "incident"
_INCIDENTS_ENVELOPE: Final = "incidents"
_ALERTS_ENVELOPE: Final = "alerts"
_NOTES_ENVELOPE: Final = "notes"
_USER_ENVELOPE: Final = "user"
_ERROR_ENVELOPE: Final = "error"

_LIMIT: Final = "limit"
_OFFSET: Final = "offset"
_MORE: Final = "more"
_TOTAL: Final = "total"

_INCIDENT_TYPE: Final = "incident"
_ALERT_TYPE: Final = "alert"
_USER_TYPE: Final = "user"
_USER_REFERENCE_TYPE: Final = "user_reference"

_TRIGGERED: Final = "triggered"
_ACKNOWLEDGED: Final = "acknowledged"
_RESOLVED: Final = "resolved"

# How PagerDuty writes a moment: UTC, to the second, with a `Z`.
_TIMESTAMP_FORMAT: Final = "%Y-%m-%dT%H:%M:%SZ"

# What PagerDuty writes in front of the note a person leaves when they resolve
# an incident from its own page. Undocumented, and observed on a real account:
# the note is stored as one more note, and this prefix is the only thing that
# marks it. The double writes it because PagerDuty does - a case says what the
# person wrote, never how PagerDuty files it.
_RESOLUTION_NOTE_PREFIX: Final = "Resolution Note: "

# A list's page, when the caller names none. PagerDuty's own default.
_A_PAGE: Final = 25

# PagerDuty's answer for an id it does not hold: a 404 whose body says so, in
# its own error shape, under its own code.
_NOT_FOUND_STATUS: Final = 404
_NOT_FOUND_CODE: Final = 2100


class Acknowledged(BaseModel):
    """One acknowledgement of a staged incident: who, when, and what they are called.

    The title is held on the person rather than the acknowledgement, as
    PagerDuty holds it, so staging one is also staging the person - and the
    adapter still has to make the second request to read it.
    """

    at: datetime
    user_id: str
    job_title: str | None = None


class Staged(BaseModel):
    """One incident, staged whole, as the case that needs it describes it.

    `alert_keys` are its alerts' keys - one per alert, several where incidents
    were merged into it - and are what `?incident_key=` matches. `notes` are
    what people wrote on it while it was going on, oldest first.
    `resolution_note` is what the person who resolved it wrote, and is filed
    after the others, prefixed the way PagerDuty files it.

    No `resolved_at` means the incident is still open; acknowledgements without
    one make it acknowledged rather than triggered.
    """

    id: str
    created_at: datetime
    resolved_at: datetime | None = None
    alert_keys: list[str] = Field(default_factory=list)
    acknowledgements: list[Acknowledged] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)
    resolution_note: str | None = None


class _State:
    """The double's whole memory, emptied between tests via `/double-control/reset`.

    In-process and non-persistent, like every other double's: it is brought up
    per run alongside the other services, and an incident surviving a restart
    would be one test leaking into the next.
    """

    def __init__(self) -> None:
        self.incidents: dict[str, Staged] = {}

    def reset(self) -> None:
        self.incidents.clear()

    def titles(self) -> dict[str, str | None]:
        """Every person any staged incident names, and what they are called."""
        return {
            acknowledgement.user_id: acknowledgement.job_title
            for incident in self.incidents.values()
            for acknowledgement in incident.acknowledgements
        }


_state = _State()

app = FastAPI(title="pagerduty-double")


@app.get("/health")
def health() -> dict[str, str]:
    """Readiness probe, so a test harness can wait for the port to answer."""
    return {"status": "ok"}


@app.post("/double-control/reset")
def reset() -> dict[str, str]:
    """Forgets every staged incident, and with them every person."""
    _state.reset()

    return {"status": "reset"}


@app.post("/double-control/incident")
def stage(incident: Staged) -> dict[str, int]:
    """Stages one incident, replacing any already staged under its id."""
    _state.incidents[incident.id] = incident

    return {"staged": len(_state.incidents)}


@app.get("/incidents")
def list_incidents(incident_key: str | None = None,
                   limit: int = _A_PAGE,
                   offset: int = 0) -> JSONResponse:
    """The incidents, or the ones carrying this key among their alerts'.

    Matched against every alert's key rather than the first, because that is
    what PagerDuty matches: an incident another was merged into answers to the
    merged one's keys too.
    """
    matching = [
        incident
        for incident in _state.incidents.values()
        if incident_key is None or incident_key in incident.alert_keys
    ]
    page = matching[offset:offset + limit]

    return JSONResponse({
        _INCIDENTS_ENVELOPE: [_an_incident(incident) for incident in page],
        _LIMIT: limit,
        _OFFSET: offset,
        _MORE: offset + len(page) < len(matching),
        _TOTAL: None
    })


@app.get("/incidents/{incident_id}")
def get_incident(incident_id: str) -> JSONResponse:
    """One incident."""
    incident = _state.incidents.get(incident_id)

    if incident is None:
        return _not_found()

    return JSONResponse({_INCIDENT_ENVELOPE: _an_incident(incident)})


@app.get("/incidents/{incident_id}/alerts")
def list_alerts(incident_id: str,
                limit: int = _A_PAGE,
                offset: int = 0) -> JSONResponse:
    """One incident's alerts, each carrying the key its sender stamped on it."""
    incident = _state.incidents.get(incident_id)

    if incident is None:
        return _not_found()

    page = incident.alert_keys[offset:offset + limit]

    return JSONResponse({
        _ALERTS_ENVELOPE: [
            {
                "id": f"{incident.id}-alert-{offset + position}",
                "type": _ALERT_TYPE,
                "alert_key": key,
                "status": _RESOLVED if incident.resolved_at else _TRIGGERED
            }
            for position, key in enumerate(page)
        ],
        _LIMIT: limit,
        _OFFSET: offset,
        _MORE: offset + len(page) < len(incident.alert_keys),
        _TOTAL: None
    })


@app.get("/incidents/{incident_id}/notes")
def list_notes(incident_id: str) -> JSONResponse:
    """One incident's notes, oldest first, the resolution note last.

    Unpaged, as PagerDuty's is.
    """
    incident = _state.incidents.get(incident_id)

    if incident is None:
        return _not_found()

    contents = [
        *incident.notes,
        *([f"{_RESOLUTION_NOTE_PREFIX}{incident.resolution_note}"]
          if incident.resolution_note is not None
          else [])
    ]

    return JSONResponse({
        _NOTES_ENVELOPE: [
            {"id": f"{incident.id}-note-{position}", "content": content}
            for position, content in enumerate(contents)
        ]
    })


@app.get("/users/{user_id}")
def get_user(user_id: str) -> JSONResponse:
    """One person some staged incident names, with their title if they hold one."""
    titles = _state.titles()

    if user_id not in titles:
        return _not_found()

    return JSONResponse({
        _USER_ENVELOPE: {
            "id": user_id,
            "type": _USER_TYPE,
            "summary": user_id,
            "job_title": titles[user_id]
        }
    })


def _an_incident(incident: Staged) -> dict[str, Any]:
    """One incident in PagerDuty's shape.

    An acknowledgement names its acknowledger rather than carrying them - an
    id, a type and a summary, which is all PagerDuty puts there - and that is
    what forces the adapter's second request for a title.
    """
    return {
        "id": incident.id,
        "type": _INCIDENT_TYPE,
        "status": _the_status_of(incident),
        "created_at": _as_text(incident.created_at),
        "resolved_at": _as_text(incident.resolved_at) if incident.resolved_at else None,
        "last_status_change_at": _as_text(_last_moved(incident)),
        "acknowledgements": [
            {
                "at": _as_text(acknowledgement.at),
                "acknowledger": {
                    "id": acknowledgement.user_id,
                    "type": _USER_REFERENCE_TYPE,
                    "summary": acknowledgement.user_id
                }
            }
            for acknowledgement in incident.acknowledgements
        ]
    }


def _the_status_of(incident: Staged) -> str:
    if incident.resolved_at:
        return _RESOLVED

    return _ACKNOWLEDGED if incident.acknowledgements else _TRIGGERED


def _last_moved(incident: Staged) -> datetime:
    """When the incident last changed status: resolved, else last acknowledged, else created."""
    if incident.resolved_at:
        return incident.resolved_at

    return max((acknowledgement.at for acknowledgement in incident.acknowledgements),
               default=incident.created_at)


def _as_text(moment: datetime) -> str:
    return moment.astimezone(UTC).strftime(_TIMESTAMP_FORMAT)


def _not_found() -> JSONResponse:
    return JSONResponse(
        status_code=_NOT_FOUND_STATUS,
        content={_ERROR_ENVELOPE: {"message": "Not Found", "code": _NOT_FOUND_CODE}}
    )


if __name__ == "__main__":
    import uvicorn

    from pagerduty_double.certificate import a_self_signed_certificate

    certificate, key = a_self_signed_certificate()
    uvicorn.run(app,
                host="localhost",
                port=DEFAULT_PORT,
                ssl_certfile=certificate,
                ssl_keyfile=key)
