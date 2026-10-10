"""The chat platform, as Argus needs it: the port, in Argus's own words.

Optional, and behind one seam, as the on-call platform is. A deployment may
talk about its incidents in Slack, somewhere else, or nowhere Argus can receive from,
so everything above this port asks it questions without knowing which platform
answers. Each platform is one adapter named for its vendor, and only that
adapter knows an envelope, a header, a field or a method name.

Split by direction, as the deployment platform is split by tier. What Argus
reads - a delivery, a person's name - is `ChatPlatformReads`, held by the web
application and the intent agent; what Argus writes - a message, a rewrite of one -
is `ChatPlatformWrites`, held by the Communicator. One adapter answers both, so
a button the Communicator posts and the press the web application reads are
spelled in one place.

What crosses the port is already translated. Going in: a person writing in an
incident's thread, a person pressing a button Argus posted, or something Argus
does not act on - which is which is decided in the adapter that can tell them
apart, not above it. Going out: a line in its parts, the thread it answers, and
whether it carries an offer to confirm; how the platform marks a word, draws a
link or a button is the adapter's.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import NamedTuple, Protocol

from argus_core.models import Reference, ReportChannel
from pydantic import BaseModel


class ChatDeliveryUnverified(Exception):
    """A delivery whose signature does not prove the platform sent it, just now.

    Raised before anything in it is read, because what a delivery can say -
    that a person pressed "resolve" - ends an incident, and a forged or
    replayed one would end an incident nobody ended.
    """


class Handshake(BaseModel):
    """The platform checking that the address answers before it sends anything
    to it. Answered with `challenge`, and nothing else is done."""

    challenge: str


class Written(BaseModel):
    """A person wrote a new reply in a thread.

    `thread` and `message` are the incident's kind of name for each, so the
    thread finds its incident through the lookup every other tool's word goes
    through, and the message is claimed once however often it is delivered.
    `person_id` is the platform's id for whoever wrote it: what a later press
    is checked against, and what their name is looked up by.
    """

    thread: Reference
    message: Reference
    person_id: str
    text: str


class Pressed(BaseModel):
    """A person pressed the button on an offer to resolve.

    `message` is the message the offer was made about - what the offer is found
    by, and so what decides whose press counts.
    """

    thread: Reference
    person_id: str
    message: Reference


class Irrelevant(BaseModel):
    """Anything else the platform said, and why it is not listened to."""

    why: str


# What a delivery turned out to say.
type Delivery = Handshake | Written | Pressed | Irrelevant


class Link(BaseModel):
    """Somewhere a reader of a line can go for more: the address, and what the
    link says."""

    url: str
    label: str


class Line(BaseModel):
    """One line Argus says, in its parts rather than in any platform's markup.

    `who` is the agent saying it. `emphasis` is the one word a reader scanning
    the channel should find without reading the line - the flag, the status,
    the verdict - with what comes before and after it, so the adapter marks it
    in its own platform's way; empty where nothing is set apart, and `text` is
    the line whole. `link` is a page that holds more than the line does.
    """

    who: str
    text: str
    emphasis: str = ""
    before_emphasis: str = ""
    after_emphasis: str = ""
    link: Link | None = None


class Offer(BaseModel):
    """A message's one button: confirming that the incident is over.

    `about` is the person's message the offer answers - what a press carries
    back, and so what decides whose press counts. `label` is what the button
    says, in the Communicator's words.
    """

    about: Reference
    label: str


class Posted(NamedTuple):
    """What came of one post: the message if it landed, and why not if it did
    not.

    Three answers in two fields, because the caller has three things to do with
    them. A message is the incident's thread from then on; a refusal worth
    another go keeps its place in the relay and is tried again; a refusal that
    is not is the end of that line, and the reason is what reaches the
    incident's timeline in its stead.
    """

    # The platform's name for the message, as a reply to it names its thread.
    message: str | None
    # The platform's own word for the refusal, or the transport's. Empty for a
    # message that arrived, because there is nothing to explain about one.
    refusal: str = ""
    # Whether trying the same message again could end differently. A throttle
    # and a workspace that did not answer say nothing about the message; every
    # other refusal is as true on the next pass as on this one.
    worth_another_go: bool = False


class ChatPlatformReads(Protocol):
    """The chat platform, for what Argus receives from it and asks of it."""

    @property
    def channel(self) -> ReportChannel:
        """Where a person's report through this platform reached Argus."""
        ...

    def parse_delivery(self, body: bytes, headers: Mapping[str, str]) -> Delivery:
        """What one delivery says, once its signature proves who sent it."""
        ...

    def person_named(self, person_id: str) -> str | None:
        """What the platform calls this person, or `None` where it cannot say."""
        ...


class ChatPlatformWrites(Protocol):
    """The chat platform, for what Argus says in it.

    Neither call raises. A refusal or an unreachable platform is answered as
    "no message", because communication is how an incident is reported and not
    how it is resolved.
    """

    @property
    def channel(self) -> ReportChannel:
        """Which platform a thread or an offer posted here belongs to, as the
        incident's references name it."""
        ...

    def post(self,
             channel: str,
             line: Line,
             thread: str | None = None,
             offer: Offer | None = None) -> Posted:
        """Posts `line` to `channel` - as a reply in `thread` where one is
        named - carrying `offer`'s button where one is given."""
        ...

    def rewrite(self, channel: str, message: str, line: Line) -> Posted:
        """Rewrites a message Argus posted to say only `line`, with no button."""
        ...
