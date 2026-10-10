from __future__ import annotations

import logging
from collections.abc import AsyncGenerator, Sequence
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated, Any, Final

import psycopg
from argus_core import Connections, DatabaseSettings, get_settings, open_pool
from argus_core.events import (
    Offered,
    OfferExpired,
    Publisher,
    ResolutionOffered,
    WithdrawalOffered,
)
from argus_core.models import IncidentStatus, Reference, Report, ReportChannel
from argus_core.schema import require_schema
from argus_core.telemetry import ARGUS_INCIDENT_ID
from argus_incidents import (
    events_into,
    events_into_connection,
    ingest_a_message,
    inside_the_incidents_trace,
    resolve_incident,
    start_incident,
    withdraw_incident,
)
from argus_incidents.repository import events, references
from chat_platform import ChatDeliveryUnverified, ChatPlatformReads
from chat_platform.slack import ChatSettings, slack_from
from code_index.records import record_pushed
from fastapi import Depends, FastAPI, Form, HTTPException, Request, Response
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from oncall_source import OnCallSettings, OnCallUnavailable
from oncall_source.pagerduty_adapter import pagerduty_from
from oncall_source.platform import OnCallDeliveryUnverified, OnCallPlatform
from opentelemetry import propagate, trace
from opentelemetry.trace import SpanKind, Tracer

from argus_web import reads
from argus_web.chat import receive_chat_delivery
from argus_web.grafana import parse_grafana_alert, reports_only_resolutions
from argus_web.oncall import OnCallDeliverySettings, receive_delivery
from argus_web.pushes import (
    SIGNATURE_HEADER,
    PushSettings,
    PushUnverified,
    Watermark,
    receive_push,
)
from argus_web.views import IncidentDetail

logger = logging.getLogger(__name__)

# The instrumentation scope this app's spans are reported under, and the
# requests that are spans at all: the one an incident's trace begins in, and a
# person ending the response. Every other route renders a page, and the
# dashboard polls, so a span for each would be noise nobody reads.
_SCOPE: Final = __name__
RECEIVE_ALERT_SPAN: Final = "receive alert"
WITHDRAW_SPAN: Final = "withdraw incident"
RESOLVE_SPAN: Final = "resolve incident"

# Who a person ending an incident from this page is recorded as. Argus has no
# users yet, so whoever pressed the button is the one person the demo has - and
# is recorded all the same, because the account must say a person did it and
# through which door, and a real name arrives with the day somebody can sign in.
THE_DEMO_USER: Final = "demo user"


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None]:
    """What this process holds for as long as it is up.

    The pool is opened here and closed here, which is the whole of why it is a
    lifespan: a process that serves requests wants connections ready before the
    first one arrives and given back when the last one has been answered. What
    a route needs, it asks for; what it asks for comes from here.

    The schema is checked and never applied. This process only reads, and a
    process that only reads is the last one that should be defining the tables
    everything else writes - it was also, while it did, the process every other
    one had to be started after.
    """
    with open_pool(DatabaseSettings.of(get_settings())) as pool:
        app.state.connections = pool.connection
        app.state.publisher = events_into(pool.connection)
        app.state.push_settings = PushSettings.of(get_settings())
        # `None` where the deployment has no on-call platform, which is how
        # its webhook comes to answer as though it did not exist.
        app.state.oncall_platform = pagerduty_from(
            OnCallSettings.of(get_settings()),
            webhook_secret=OnCallDeliverySettings.of(get_settings()).pagerduty_webhook_secret
        )
        # `None` where the deployment has no chat workspace, for the same reason.
        app.state.chat_platform = slack_from(ChatSettings.of(get_settings()))

        with pool.connection() as conn:
            require_schema(conn)

        yield


app = FastAPI(lifespan=lifespan)


def connections_of(request: Request) -> Connections:
    """Where a route gets its connections: from the process that is serving it.

    A dependency rather than a module-level reach, so a route says in its own
    signature that it touches the database and can be handed something else
    entirely by whoever is calling it.
    """
    connections: Connections = request.app.state.connections

    return connections


def publisher_of(request: Request) -> Publisher:
    """The subscriber this process files events through, for the same reason."""
    publisher: Publisher = request.app.state.publisher

    return publisher


def push_settings_of(request: Request) -> PushSettings:
    """What the push webhook trusts and watches, read once at startup.

    A dependency for the reason the connections are one: the route says in its
    signature that it is configured, and a test can hand it a different
    deployment without an environment anywhere near it.
    """
    settings: PushSettings = request.app.state.push_settings

    return settings


def oncall_platform_of(request: Request) -> OnCallPlatform | None:
    """The on-call platform deliveries come from, or `None` where there is none.

    A dependency for the reason the push settings are one: the route says in
    its signature what it reads from, and a test stands a platform in without
    anybody's API.
    """
    platform: OnCallPlatform | None = request.app.state.oncall_platform

    return platform


def chat_platform_of(request: Request) -> ChatPlatformReads | None:
    """The chat platform deliveries come from, or `None` where there is none.

    A dependency for the reason the on-call platform is one.
    """
    platform: ChatPlatformReads | None = request.app.state.chat_platform

    return platform


def tracer_of() -> Tracer:
    """What a route makes its spans with: the process's own tracer.

    Looked up per request rather than once at import, so an app built before
    telemetry was started still reports to it. A dependency for the reason the
    connections are one: a test hands in a tracer whose spans it can read back.
    """
    return trace.get_tracer(_SCOPE)


type UsingConnections = Annotated[Connections, Depends(connections_of)]
type Publishing = Annotated[Publisher, Depends(publisher_of)]
type UsingPushSettings = Annotated[PushSettings, Depends(push_settings_of)]
type UsingOnCallPlatform = Annotated[OnCallPlatform | None, Depends(oncall_platform_of)]
type UsingChatPlatform = Annotated[ChatPlatformReads | None, Depends(chat_platform_of)]
type Tracing = Annotated[Tracer, Depends(tracer_of)]

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
def receive_alert(payload: dict[str, Any],
                  connections: UsingConnections,
                  publisher: Publishing,
                  tracer: Tracing) -> dict[str, str | None]:
    """`argus_web`'s only incident-domain entrypoint (spec §7.9): validates
    and normalizes the payload into an `Alert` domain object, then calls the
    Orchestrator's entrypoint in-process - never the raw payload.

    Answers as soon as the incident exists, with its id. The walk belongs to a
    worker: an investigation run here would hold this connection open for its
    whole length, and a caller that gave up would leave it running with nobody
    to answer.

    A webhook saying only that rules stopped firing opens nothing, and is
    answered with no incident. One that cannot be read is refused with a `422`.

    Received inside a span of its own, which is where the incident's trace
    begins: the incident keeps the span's context, and every walk of it
    continues from there."""
    with tracer.start_as_current_span(RECEIVE_ALERT_SPAN, kind=SpanKind.SERVER) as span:
        if reports_only_resolutions(payload):
            return {"incident_id": None}

        try:
            alert = parse_grafana_alert(payload)
        except (LookupError, TypeError, ValueError) as unreadable:
            # The sender's input rather than a fault here, so refused rather
            # than failed: Grafana sends a failure again, and a payload that
            # could not be read once reads no better the next time.
            logger.warning("alert payload rejected", exc_info=True)
            raise HTTPException(
                status_code=422, detail=f"the alert could not be read: {unreadable!r}"
            ) from unreadable

        received_in: dict[str, str] = {}
        propagate.inject(received_in)
        incident_id = start_incident(alert, connections, events_into_connection,
                                     trace_context=received_in)
        span.set_attribute(ARGUS_INCIDENT_ID, incident_id)

        return {"incident_id": incident_id}


@app.post("/webhooks/github/push", status_code=202)
async def receive_github_push(request: Request,
                              connections: UsingConnections,
                              settings: UsingPushSettings) -> dict[str, str | None]:
    """Records that the Target Service's repository has moved (spec §11).

    The edge of an edge-triggered notification, level-triggered reconciliation
    pair: one row is written and nothing is indexed here. The catch-up pass
    closes the gap, so a delivery that never arrives costs a delay rather than
    a permanently stale index - and indexing in this process would install an
    ONNX runtime to serve a page.

    Async, unlike every other route here, because the signature is over the
    bytes that arrived and reading those is the one thing FastAPI will not
    hand a synchronous handler. The behavior - verification, the ref filter,
    what gets recorded - lives in `pushes.receive_push`; this is registration
    only.

    `202` for a push that was recorded and for one there was nothing to record
    about alike. Both are deliveries that arrived intact, and a webhook that
    answers an error for news it does not need is one somebody disables."""
    try:
        recorded = receive_push(
            await request.body(),
            request.headers.get(SIGNATURE_HEADER),
            settings=settings,
            record_pushed=_the_watermark_kept_by(connections)
        )
    except PushUnverified as refused:
        raise HTTPException(status_code=401, detail=str(refused)) from refused

    return {"recorded": recorded}


@app.post("/webhooks/oncall", status_code=202)
async def receive_oncall_delivery(request: Request,
                                  platform: UsingOnCallPlatform,
                                  connections: UsingConnections,
                                  publisher: Publishing,
                                  tracer: Tracing) -> dict[str, str]:
    """Where the on-call platform tells Argus what happened to its incidents.

    One delivery is acted on - a person resolving an incident Argus has - and
    what that does lives in `oncall.receive_delivery`; this is registration
    and the answer the platform acts on. Async for the reason the push webhook
    is: the signature is over the bytes that arrived.

    `404` where the deployment has no on-call platform, which is optional.
    `401` for a delivery it did not sign, which the platform drops. `503` when
    its API cannot be read mid-match, which the platform sends again, so a
    blip never loses a person's word. `202` for everything else it sends,
    acted on or not: received intact is received.

    Needs a public URL to be reached at all - an ingress, or a tunnel for a
    demo - which is the deployment's to give it.
    """
    if platform is None:
        raise HTTPException(status_code=404, detail="no on-call platform is configured")

    try:
        receive_delivery(
            await request.body(),
            request.headers,
            platform=platform,
            record=_TheIncidentRecord(connections, publisher, tracer)
        )
    except OnCallDeliveryUnverified as refused:
        # Most often the deployment holding a different secret from the
        # subscription's, and the platform drops a refusal without retrying -
        # so this line is the only trace that a person's word was turned away.
        logger.warning("on-call delivery refused", extra={"reason": str(refused)})
        raise HTTPException(status_code=401, detail=str(refused)) from refused
    except OnCallUnavailable as unavailable:
        logger.warning("on-call platform unreadable", exc_info=True)
        raise HTTPException(status_code=503, detail=str(unavailable)) from unavailable

    return {"received": "true"}


@app.post("/webhooks/slack/events")
async def receive_chat_event(request: Request,
                             platform: UsingChatPlatform,
                             connections: UsingConnections,
                             publisher: Publishing,
                             tracer: Tracing) -> dict[str, str]:
    """Where the chat platform tells Argus what was posted where it can see.

    One thing is acted on - a person replying in an incident's thread, which is
    ingested on that incident - and what that does lives in
    `chat.receive_chat_delivery`; this is registration and the answer the
    platform acts on.
    """
    return await _a_chat_delivery(request, platform, connections, publisher, tracer)


@app.post("/webhooks/slack/interactions")
async def receive_chat_interaction(request: Request,
                                   platform: UsingChatPlatform,
                                   connections: UsingConnections,
                                   publisher: Publishing,
                                   tracer: Tracing) -> dict[str, str]:
    """Where the chat platform tells Argus a button on one of its messages was
    pressed.

    A door of its own only because Slack is configured with a separate address
    for interactions; what is behind it is the same handling as the events'.
    """
    return await _a_chat_delivery(request, platform, connections, publisher, tracer)


async def _a_chat_delivery(request: Request,
                           platform: ChatPlatformReads | None,
                           connections: Connections,
                           publisher: Publisher,
                           tracer: Tracer) -> dict[str, str]:
    """Both chat doors' handling, and the answer the platform acts on.

    Async for the reason the push webhook is: the signature is over the bytes
    that arrived.

    `404` where the deployment has no chat workspace, which is optional. `401`
    for a delivery it did not sign. `200` for everything else, acted on or not,
    and inside the platform's three seconds: received intact is received, and a
    delivery answered late is one the platform sends again. The challenge is
    the answer where the platform is checking the address.

    Needs a public URL to be reached at all - an ingress, or a tunnel for a
    demo - which is the deployment's to give it.
    """
    if platform is None:
        raise HTTPException(status_code=404, detail="no chat platform is configured")

    try:
        challenge = receive_chat_delivery(
            await request.body(),
            request.headers,
            platform=platform,
            record=_TheChatRecord(_TheIncidentRecord(connections, publisher, tracer),
                                  connections)
        )
    except ChatDeliveryUnverified as refused:
        # Most often the deployment holding a different signing secret from the
        # app's, and nothing else would show that a person's words were turned
        # away.
        logger.warning("chat delivery refused", extra={"reason": str(refused)})
        raise HTTPException(status_code=401, detail=str(refused)) from refused

    return {"challenge": challenge} if challenge is not None else {"received": "true"}


class _TheChatRecord:
    """The incident record, as a delivery from the chat platform reaches it.

    Finding, resolving and withdrawing are the incident record's, unchanged - a
    person ending the incident from a thread ends it inside the incident's
    trace, as from anywhere else. Ingesting and finding an offer are the chat's
    own.
    """

    def __init__(self, incidents: _TheIncidentRecord, connections: Connections) -> None:
        self._incidents = incidents
        self._connections = connections

    def incident_known_as(self, kind: str, values: Sequence[str]) -> str | None:
        return self._incidents.incident_known_as(kind, values)

    def ingest(self, incident_id: str, message: Reference, person_id: str, text: str) -> bool:
        return ingest_a_message(incident_id, message, person_id, text, self._connections)

    def offer_about(self, incident_id: str, message: Reference) -> Offered | None:
        with self._connections() as conn:
            recorded = events.get_by_incident(conn, incident_id)

        return next((event for event in recorded
                     if isinstance(event, ResolutionOffered | WithdrawalOffered)
                     and event.message == message),
                    None)

    def offer_expired(self, incident_id: str, message: Reference) -> bool:
        with self._connections() as conn:
            recorded = events.get_by_incident(conn, incident_id)

        return any(isinstance(event, OfferExpired) and event.message == message
                   for event in recorded)

    def resolve(self, incident_id: str, reported: Report) -> bool:
        return self._incidents.resolve(incident_id, reported)

    def withdraw(self, incident_id: str, reported: Report) -> bool:
        return self._incidents.withdraw(incident_id, reported)


class _TheIncidentRecord:
    """The incident record, as a delivery from the on-call or the chat
    platform reaches it.

    A resolution or a withdrawal here is made inside the incident's own trace,
    as one from the page is: a person ending the incident is part of its
    story, wherever they said it.
    """

    def __init__(self, connections: Connections, publisher: Publisher, tracer: Tracer) -> None:
        self._connections = connections
        self._publisher = publisher
        self._tracer = tracer

    def incident_known_as(self, kind: str, values: Sequence[str]) -> str | None:
        with self._connections() as conn:
            return references.get_incident_by_values(conn, kind, values)

    def know_it_as(self, incident_id: str, reference: Reference) -> None:
        with self._connections() as conn:
            references.add(conn, incident_id, [reference])
            conn.commit()

    def resolve(self, incident_id: str, reported: Report) -> bool:
        with self._connections() as conn:
            kept = reads.read_trace_context(conn, incident_id) or {}

        with inside_the_incidents_trace(incident_id, kept, RESOLVE_SPAN,
                                        kind=SpanKind.SERVER, tracer=self._tracer):
            return resolve_incident(incident_id, reported, self._connections, self._publisher)

    def withdraw(self, incident_id: str, reported: Report) -> bool:
        """Withdraws the incident inside its own trace, as a resolution is."""
        with self._connections() as conn:
            kept = reads.read_trace_context(conn, incident_id) or {}

        with inside_the_incidents_trace(incident_id, kept, WITHDRAW_SPAN,
                                        kind=SpanKind.SERVER, tracer=self._tracer):
            return withdraw_incident(incident_id, reported, self._connections, self._publisher)


def _the_watermark_kept_by(connections: Connections) -> Watermark:
    """Where a verified push is written down.

    The only line in this process that names the index at all, and it names
    the row rather than the store: `code_index.records` is Postgres and
    nothing else, which is what lets the web process record a push without
    installing a vector store or an embedding model to do it.
    """
    def record(repository: str, sha: str, /) -> None:
        with connections() as conn:
            record_pushed(conn, repository, sha)

    return record


@app.post("/incidents/{incident_id}/withdraw")
def withdraw(incident_id: str,
             connections: UsingConnections,
             publisher: Publishing,
             tracer: Tracing) -> dict[str, str]:
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

    Done inside the incident's own trace, since a person stopping the response
    is part of the incident's story.
    """
    with connections() as conn:
        kept = reads.read_trace_context(conn, incident_id)

    if kept is None:
        raise HTTPException(status_code=404, detail=f"no incident {incident_id}")

    with inside_the_incidents_trace(incident_id, kept, WITHDRAW_SPAN,
                                    kind=SpanKind.SERVER, tracer=tracer):
        withdrawn = withdraw_incident(
            incident_id,
            Report(by=THE_DEMO_USER, channel=ReportChannel.ARGUS_UI),
            connections,
            publisher
        )

        if not withdrawn:
            # Inside the trace, so the line carries the incident it is about.
            logger.info("withdrawal refused")

    if not withdrawn:
        raise HTTPException(
            status_code=409, detail=f"incident {incident_id} has already ended"
        )

    return {"incident_id": incident_id, "status": IncidentStatus.WITHDRAWN}


@app.post("/incidents/{incident_id}/resolve")
def resolve(incident_id: str,
            response: Response,
            connections: UsingConnections,
            publisher: Publishing,
            tracer: Tracing,
            note: Annotated[str, Form()] = "") -> dict[str, str]:
    """Records that a person reports the incident over, at their say-so.

    The withdrawal's sibling, and the same arrangement: the incident is named,
    the person and what they wrote are passed on, and the incident record
    answers. Whether a resolution is accepted is a fact about the incident.

    The note is optional and arrives as a form field, because that is what the
    page's control sends. A box left empty, or holding only spaces, is a person
    who said nothing - recorded as no note rather than as an empty one.

    A refusal is a `409`. An incident withdrawn, disproven or already resolved
    has ended for its own reason, and answering "done" would have somebody
    believe they had closed it.

    The page is told to reload on success. An incident Argus had already ended
    has a page that stopped polling, so without it nothing would show the
    person what their press did.
    """
    with connections() as conn:
        kept = reads.read_trace_context(conn, incident_id)

    if kept is None:
        raise HTTPException(status_code=404, detail=f"no incident {incident_id}")

    with inside_the_incidents_trace(incident_id, kept, RESOLVE_SPAN,
                                    kind=SpanKind.SERVER, tracer=tracer):
        resolved = resolve_incident(
            incident_id,
            Report(by=THE_DEMO_USER, channel=ReportChannel.ARGUS_UI,
                   note=note.strip() or None),
            connections,
            publisher
        )

        if not resolved:
            # Inside the trace, so the line carries the incident it is about.
            logger.info("resolution refused")

    if not resolved:
        raise HTTPException(
            status_code=409, detail=f"incident {incident_id} cannot be resolved"
        )

    response.headers["HX-Refresh"] = "true"

    return {"incident_id": incident_id, "status": IncidentStatus.RESOLVED}


@app.get("/", response_class=HTMLResponse)
def live_page(request: Request, connections: UsingConnections) -> HTMLResponse:
    """What is happening now: the front door.

    An incident rather than a list of them. Somebody who opens Argus during an
    incident came for the incident, and a list in front of it is one click of
    indirection ahead of the only thing they wanted.
    """
    with connections() as conn:
        return templates.TemplateResponse(
            request, "live.html", {"incident": reads.read_live_incident(conn)}
        )


@app.get("/now", response_class=HTMLResponse)
def live_body(request: Request, connections: UsingConnections) -> HTMLResponse:
    """The front page's own poll, and the whole of what it swaps in.

    It never stops asking, unlike an incident's walk. An incident can finish;
    the front page cannot, because the next alert is exactly what somebody
    watching this screen is waiting for - and a page that stopped polling when
    the incident it happened to be showing resolved would never show them.
    """
    with connections() as conn:
        return templates.TemplateResponse(
            request, "live_body.html", {"incident": reads.read_live_incident(conn)}
        )


@app.get("/history", response_class=HTMLResponse)
def history_page(request: Request, connections: UsingConnections) -> HTMLResponse:
    """Every incident Argus has been woken for, newest first.

    The ordering is the repository's. Deciding what "recent" means would be
    this page having an opinion about incidents, which is not its job.
    """
    with connections() as conn:
        return templates.TemplateResponse(
            request, "history.html", {"incidents": reads.read_history(conn)}
        )


@app.get("/history/list", response_class=HTMLResponse)
def history_list(request: Request, connections: UsingConnections) -> HTMLResponse:
    """The list on its own, for the history's poll to swap in.

    It never stops asking, unlike an incident's walk: an incident reaches a
    terminal status and has nothing further to say, while the next incident is
    exactly what somebody watching this screen is waiting for.
    """
    with connections() as conn:
        return templates.TemplateResponse(
            request, "history_list.html", {"incidents": reads.read_history(conn)}
        )


@app.get("/incidents/{incident_id}", response_class=HTMLResponse)
def incident_page(request: Request,
                  incident_id: str,
                  connections: UsingConnections) -> HTMLResponse:
    """One incident's whole walk: the alert it opened on, every ranked
    candidate with what was tried for it, and the transitions it went through."""
    with connections() as conn:
        incident = _an_incident_or_404(conn, incident_id)
        story = reads.read_story(conn, incident_id)

    return templates.TemplateResponse(
        request, "incident.html", {"incident": incident, "story": story}
    )


@app.get("/incidents/{incident_id}/walk", response_class=HTMLResponse)
def incident_walk(request: Request,
                  incident_id: str,
                  connections: UsingConnections) -> HTMLResponse:
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
    with connections() as conn:
        incident = _an_incident_or_404(conn, incident_id)
        story = reads.read_story(conn, incident_id)

    return templates.TemplateResponse(
        request,
        "walk.html",
        {"incident": incident, "story": story, "polled": True},
    )


@app.get("/incidents/{incident_id}/postmortem", response_class=HTMLResponse)
def postmortem_page(request: Request,
                    incident_id: str,
                    connections: UsingConnections) -> HTMLResponse:
    """The postmortem, where one has been written.

    Its own page rather than a section of the incident's: it is the largest
    body Argus writes, and the page beside it is polled every two seconds. An
    incident with none renders the page saying so - absence is an answer here,
    not a failure.

    A person's resolution is shown beside the document, whichever came first:
    one written before the report is not rewritten, and the person who ended
    the incident is part of what a reader of its write-up is owed.
    """
    with connections() as conn:
        incident = _an_incident_or_404(conn, incident_id)
        postmortem = reads.read_postmortem(conn, incident_id)
        resolution = reads.read_resolution(conn, incident_id)

    return templates.TemplateResponse(
        request,
        "postmortem.html",
        {"incident": incident, "postmortem": postmortem, "resolution": resolution},
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
