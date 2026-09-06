from __future__ import annotations

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import psycopg
from argus_core.db import connect
from argus_core.models.incident_status import IncidentStatus
from argus_core.schema import create_schema
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from orchestrator.intake import start_incident
from orchestrator.withdrawal import withdraw_incident

from argus_web import reads
from argus_web.grafana import parse_grafana_alert
from argus_web.views import IncidentDetail


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None]:
    with connect() as conn:
        create_schema(conn)
    yield


app = FastAPI(lifespan=lifespan)

# Argus's own mark and the one script the page needs, both shipped with the
# module and mounted from a path relative to it, so they resolve the same in
# the container as in a local checkout.
app.mount(
    "/assets",
    StaticFiles(directory=Path(__file__).parent / "assets"),
    name="assets",
)

templates = Jinja2Templates(directory=Path(__file__).parent / "templates")


def _in_utc(moment: datetime, pattern: str = "%Y-%m-%d %H:%M") -> str:
    """A moment, rendered in UTC and saying so.

    The zone is written out rather than assumed. The Target Service's console
    stamps its minutes in UTC and labels them; an unlabelled time on this
    screen reads as local, and beside that console it looks as though the two
    disagree about when the incident happened.

    Converted rather than trusted: the value arrives from a `TIMESTAMPTZ` in
    whatever zone the connection is set to, and formatting it as it comes would
    make the label a guess.
    """
    return f"{moment.astimezone(UTC).strftime(pattern)} UTC"


def _on_the_clock(moment: datetime, pattern: str = "%H:%M:%S") -> str:
    """A moment in UTC, unlabelled - for a column whose heading says UTC once.

    The same conversion `_in_utc` does and none of its suffix: a table that
    repeats the zone on every row of forty spends a column's width saying one
    thing forty times, and on a screen being read from across a room that width
    is the message column's.
    """
    return moment.astimezone(UTC).strftime(pattern)


templates.env.filters["utc"] = _in_utc
templates.env.filters["clock"] = _on_the_clock


@app.post("/webhooks/alerts", status_code=202)
def receive_alert(payload: dict[str, Any]) -> dict[str, str]:
    """`argus_web`'s only incident-domain entrypoint (spec §7.9): validates
    and normalizes the payload into an `Alert` domain object, then calls the
    Orchestrator's entrypoint in-process - never the raw payload.

    Answers as soon as the incident exists, with its id. The walk belongs to a
    worker: an investigation run here would hold this connection open for its
    whole length, and a caller that gave up would leave it running with nobody
    to answer."""
    alert = parse_grafana_alert(payload)
    incident_id = start_incident(alert)
    return {"incident_id": incident_id}


@app.post("/incidents/{incident_id}/withdraw")
def withdraw(incident_id: str) -> dict[str, str]:
    """Takes an incident back from Argus, at somebody's say-so.

    The one thing this application exposes that changes an incident, and it is
    one because it is the human's own act rather than Argus's: it stops the
    response and puts back what the response changed. Everything else here
    renders what was recorded.

    It decides nothing all the same. The incident is named and the Orchestrator
    answers; whether a withdrawal is permitted is a fact about the incident, and
    the incident does not live in this process.

    A refusal is a `409` rather than a quiet success. An incident that has
    already ended cannot be stopped, and answering as though it had been would
    have somebody believe they had taken back a mitigation that is still
    holding the service up.
    """
    with connect() as conn:
        _an_incident_or_404(conn, incident_id)

    if not withdraw_incident(incident_id):
        raise HTTPException(
            status_code=409, detail=f"incident {incident_id} has already ended"
        )

    return {"incident_id": incident_id, "status": IncidentStatus.WITHDRAWN}


@app.get("/", response_class=HTMLResponse)
def live_page(request: Request) -> HTMLResponse:
    """What is happening now: the front door.

    An incident rather than a list of them. Somebody who opens Argus during an
    incident came for the incident, and a list in front of it is one click of
    indirection ahead of the only thing they wanted.
    """
    with connect() as conn:
        return templates.TemplateResponse(
            request, "live.html", {"incident": reads.read_live_incident(conn)}
        )


@app.get("/now", response_class=HTMLResponse)
def live_body(request: Request) -> HTMLResponse:
    """The front page's own poll, and the whole of what it swaps in.

    It never stops asking, unlike an incident's walk. An incident can finish;
    the front page cannot, because the next alert is exactly what somebody
    watching this screen is waiting for - and a page that stopped polling when
    the incident it happened to be showing resolved would never show them.
    """
    with connect() as conn:
        return templates.TemplateResponse(
            request, "live_body.html", {"incident": reads.read_live_incident(conn)}
        )


@app.get("/history", response_class=HTMLResponse)
def history_page(request: Request) -> HTMLResponse:
    """Every incident Argus has been woken for, newest first.

    The ordering is the repository's. Deciding what "recent" means would be
    this page having an opinion about incidents, which is not its job.
    """
    with connect() as conn:
        return templates.TemplateResponse(
            request, "history.html", {"incidents": reads.read_history(conn)}
        )


@app.get("/history/list", response_class=HTMLResponse)
def history_list(request: Request) -> HTMLResponse:
    """The list on its own, for the history's poll to swap in.

    It never stops asking, unlike an incident's walk: an incident reaches a
    terminal status and has nothing further to say, while the next incident is
    exactly what somebody watching this screen is waiting for.
    """
    with connect() as conn:
        return templates.TemplateResponse(
            request, "history_list.html", {"incidents": reads.read_history(conn)}
        )


@app.get("/incidents/{incident_id}", response_class=HTMLResponse)
def incident_page(request: Request, incident_id: str) -> HTMLResponse:
    """One incident's whole walk: the alert it opened on, every ranked
    candidate with what was tried for it, and the transitions it went through."""
    with connect() as conn:
        incident = _an_incident_or_404(conn, incident_id)
        story = reads.read_story(conn, incident_id)

    return templates.TemplateResponse(
        request, "incident.html", {"incident": incident, "story": story}
    )


@app.get("/incidents/{incident_id}/walk", response_class=HTMLResponse)
def incident_walk(request: Request, incident_id: str) -> HTMLResponse:
    """The part of the page that changes while the incident runs.

    Served on its own so a poll swaps exactly what can move. The fragment
    carries its own instruction to poll again, so an incident that has since
    finished answers without one and the polling stops - see `walk.html`.

    `polled` tells the fragment it is the whole of the reply rather than part
    of a page. The withdraw button lives in the sticky header and is refreshed
    from here out of band, and an out-of-band swap only means anything in
    content htmx is swapping in - rendered into the full page it would put a
    second button on screen.
    """
    with connect() as conn:
        incident = _an_incident_or_404(conn, incident_id)
        story = reads.read_story(conn, incident_id)

    return templates.TemplateResponse(
        request,
        "walk.html",
        {"incident": incident, "story": story, "polled": True},
    )


@app.get("/incidents/{incident_id}/postmortem", response_class=HTMLResponse)
def postmortem_page(request: Request, incident_id: str) -> HTMLResponse:
    """The postmortem, where one has been written.

    Its own page rather than a section of the incident's: it is the largest
    body Argus writes, and the page beside it is polled every two seconds. An
    incident with none renders the page saying so - absence is an answer here,
    not a failure.
    """
    with connect() as conn:
        incident = _an_incident_or_404(conn, incident_id)
        postmortem = reads.read_postmortem(conn, incident_id)

    return templates.TemplateResponse(
        request,
        "postmortem.html",
        {"incident": incident, "postmortem": postmortem},
    )


def _an_incident_or_404(conn: psycopg.Connection, incident_id: str) -> IncidentDetail:
    """The incident, or the answer that there is no such incident.

    A 404 rather than an empty page: an id that never existed has no walk to be
    empty, and rendering one for it invents a record.
    """
    incident = reads.read_incident(conn, incident_id)
    if incident is None:
        raise HTTPException(status_code=404, detail=f"no incident {incident_id}")

    return incident
