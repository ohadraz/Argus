"""The feature-flag provider, as an Unleash server answers for it.

The only place in Argus that knows Unleash's wire shape: its routes, which of its
two credentials each one is asked under, where in each answer the fact asked about
lives, and the names its event log records a toggle under. Everything above the
port asks for what it wants and gets Argus's own values back.

Two credentials, and they are not interchangeable. The evaluation (frontend)
token can say which flags are on and cannot change one; the admin token changes a
flag and is the only one the provider serves its event log to. So there are two
adapters. `UnleashFrontend` holds the first alone and is the read tier's - its
settings have no field to put the second in, which is what makes `argus-read-mcp`
incapable of mutation rather than merely disinclined (spec §13). `Unleash` holds
both and is the write tier's: a read credential inside a write process is
harmless, and the reverse is the thing the tier split exists to prevent.

Four surfaces, failing differently. Evaluation says which flags are on now, and
an outage there must never read as "none is". The admin read of one flag says
what the provider itself holds for it, dated by the provider's own clock - which
is what a change is planned over, since evaluation is a cache and says nothing of
when. The event log says what changed, in which direction and by whom - which
current state cannot, since a flag switched off into an incident evaluates exactly
like one off for a year. And the admin toggle changes a flag, and is not done
until evaluation agrees: Unleash accepts the write before the change reaches
evaluation, and a caller trusting the write would judge a service nothing had yet
been done to.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from typing import Any, Final

import httpx2
from core import AdapterSettings, parse_iso, to_iso
from core.applying import known_not_applied
from core.models import FlagChange, FlagState, FlagUndo
from pydantic import Field
from pydantic_settings import SettingsConfigDict

from flag_provider.failures import FlagProviderUnavailable, FlagWriteFailed

logger = logging.getLogger(__name__)

# The routes, as Unleash spells them. Evaluation is the frontend API, answered to
# the evaluation credential; the event log is the admin API's.
EVALUATION_PATH: Final = "/api/frontend"
EVENTS_PATH: Final = "/api/admin/events"

# How a request carries its credential. Unleash takes the token bare, with no
# scheme in front of it.
AUTHORIZATION_HEADER: Final = "Authorization"
# Where the provider's answer says when it was sent - for a write, when the write
# was made; for the admin read of a flag, when the flag was as it says.
DATE_HEADER: Final = "Date"

# The admin read of one flag: its `featureSchema`, listing each environment the
# flag can be used in and whether it is on there.
FEATURE_ENVIRONMENTS: Final = "environments"
ENVIRONMENT_NAME: Final = "name"
ENVIRONMENT_ENABLED: Final = "enabled"

# Evaluation's answer: the toggles that evaluate true, each by name. A flag that
# is off is absent rather than present and false - but `enabled` is honoured
# where it appears.
TOGGLES: Final = "toggles"
TOGGLE_NAME: Final = "name"
TOGGLE_ENABLED: Final = "enabled"

# The event log's answer, and the fields of one of its rows.
EVENTS: Final = "events"
EVENT_ID: Final = "id"
EVENT_TYPE: Final = "type"
EVENT_FLAG: Final = "featureName"
EVENT_ENVIRONMENT: Final = "environment"
EVENT_CREATED_AT: Final = "createdAt"
EVENT_CREATED_BY: Final = "createdBy"

# The provider's own names for the two events that change what a service
# evaluates. Everything else in its log - features created, strategies added,
# tokens issued - left evaluation where it was, and so is not a change to undo.
ENABLED_EVENT: Final = "feature-environment-enabled"
DISABLED_EVENT: Final = "feature-environment-disabled"

# The method the admin write is made with, as the classification of its
# failure is asked about it.
_THE_WRITE: Final = "POST"

REQUEST_TIMEOUT_SECONDS: Final = 10.0

# How long to keep asking whether a change became visible. Propagation is
# sub-second in practice; this is the bound on "it never did", not the expected
# wait.
_EVALUATION_ATTEMPTS: Final = 25
_SECONDS_BETWEEN_ATTEMPTS: Final = 0.2

# How the wait between looks is spent. Injected so that a change which never
# becomes visible is a case a test can afford, rather than five real seconds.
Sleeper = Callable[[float], None]


class UnleashFrontendSettings(AdapterSettings):
    """What it takes to ask the provider which flags are on.

    The evaluation credential and where to send it, and deliberately nothing
    more. The admin credential is absent because there is no field here to put
    it in: the read tier is incapable of mutation rather than disinclined
    (spec §13), and a type that cannot name that credential is how it stays true
    on the day somebody puts one in the environment.

    Read from the variables a deployment always set - `UNLEASH_BASE_URL`,
    `UNLEASH_FRONTEND_TOKEN` - under the provider's own prefix, on the base
    every vendor's settings share (`.env`, the rest ignored, frozen). The
    defaults are the Target Environment's provider.
    """

    model_config = SettingsConfigDict(env_prefix="UNLEASH_")

    base_url: str = Field(default="http://localhost:4242")
    # Scoped to one environment by the provider, so the environment is the
    # token's rather than a parameter: a caller cannot ask about one the read
    # tier was not given access to.
    frontend_token: str = Field(default="default:production.argus-demo-frontend-token")


class UnleashSettings(UnleashFrontendSettings):
    """What the write tier is allowed to know, which is both credentials and
    where a change is addressed.

    The admin token changes a flag and reads the event log; the evaluation token
    confirms a change became visible. Empty by default, so a misconfigured write
    server fails loudly rather than silently authenticating as nobody.

    `project` and `environment` are where the admin API addresses a flag, and
    the environment is also the one whose changes the history reports: one
    Target Service maps to one environment, and a flag toggled in another did
    not cause its incident.

    `actor` is the name the provider attributes Argus's own writes to - the
    username on the admin credential, seeded by the Target Environment's compose
    file. It is what tells a change Argus made from one a human made. Empty is
    the honest setting where Argus and its operators share one credential, and
    then no change is said to be Argus's own or not.
    """

    admin_token: str = Field(default="")
    project: str = Field(default="default")
    environment: str = Field(default="production")
    actor: str = Field(default="Argus")


class UnleashFrontend:
    """The reads port, answered by one Unleash under the evaluation credential.

    A class because every request shares one configured client. `transport` is
    where a test puts the provider; left out, requests go over the network.
    """

    def __init__(self,
                 settings: UnleashFrontendSettings,
                 transport: httpx2.BaseTransport | None = None) -> None:
        self._base_url = settings.base_url
        self._client = _a_client(settings.base_url, settings.frontend_token, transport)

    def enabled(self) -> list[str]:
        """The flags evaluating true now, in the order the provider lists them.

        Any failure to get an answer - unreachable host, error status, unreadable
        body - becomes `FlagProviderUnavailable`. None of them may become
        "nothing is enabled".
        """
        try:
            body = self._evaluation()
        except Exception as error:
            raise FlagProviderUnavailable(
                f"could not read flag state from [{self._base_url}{EVALUATION_PATH}]: {error}"
            ) from error

        return _the_enabled_in(body)

    def _evaluation(self) -> dict[str, Any]:
        """The provider's evaluation answer, as it sent it, failing as it failed.

        Read by the write adapter beside it too, which confirms its own writes by
        this read and has to say what went wrong in the provider's words rather
        than in an outage's.
        """
        response = self._client.get(EVALUATION_PATH)
        response.raise_for_status()
        body: dict[str, Any] = response.json()

        return body


class Unleash:
    """Both flag ports and the audit, answered by one Unleash server.

    Holds the admin credential, for the write, the admin read and the event log,
    and the evaluation credential, for confirming a write as the service sees it
    - the evaluation the Target Service reads is answered to that credential.
    """

    def __init__(self,
                 settings: UnleashSettings,
                 transport: httpx2.BaseTransport | None = None,
                 sleep: Sleeper = time.sleep) -> None:
        self._settings = settings
        self._frontend = UnleashFrontend(settings, transport)
        self._admin = _a_client(settings.base_url, settings.admin_token, transport)
        self._sleep = sleep

    def enabled(self) -> list[str]:
        """The flags evaluating true now, read as the read tier reads them."""
        return self._frontend.enabled()

    def state_of(self, flag: str, /) -> FlagState:
        """Whether `flag` is on in the configured environment, as the admin API
        holds it, dated by the answer's own `Date`.

        Never read from evaluation, which is a cache and says neither what the
        provider holds nor when. The configured environment alone: the answer
        lists every environment the flag can be used in, and the one listed first
        is not the one asked about.

        Any failure to get a dated state - unreachable host, error status (a flag
        that does not exist among them), unreadable body, a flag not in the
        configured environment, a missing or unreadable `Date` - becomes
        `FlagProviderUnavailable`. Not dated by this process instead: the date is
        what the change is later made over, and a read with no time of the
        provider's own cannot be compared with its history.
        """
        path = self._feature_path(flag)

        try:
            response = self._admin.get(path)
            response.raise_for_status()
            enabled = self._enabled_here_in(response.json())
            read_at = _the_date_on(response)
        except Exception as error:
            raise FlagProviderUnavailable(
                f"could not read flag [{flag}] at [{self._settings.base_url}{path}]: {error}"
            ) from error

        return FlagState(enabled=enabled, read_at=read_at)

    def set(self, flag: str, enabled: bool, /) -> FlagUndo:
        """Sets `flag` on or off in the configured environment and waits until it is.

        Returns the undo descriptor: the state that existed before, which is what
        restores it. `was_enabled` is the opposite of what is being set rather
        than a fresh reading of the flag - this is only ever called to move a flag
        from one state to the other, and re-reading it here would open a window in
        which the answer changed between the two calls without making the record
        any truer.

        Raises `FlagWriteFailed` unless the provider accepted the change *and*
        the change became visible to evaluation, saying what it left behind. A
        write the provider never took left nothing; one whose answer was lost may
        have flipped the flag, and says nothing either way. One the provider took
        and nobody saw evaluating has flipped it, so the failure carries what puts
        it back.
        """
        path = self._toggle_path(flag, enabled)

        try:
            response = self._admin.post(path)
            response.raise_for_status()
        except Exception as error:
            raise FlagWriteFailed(
                f"could not set flag [{flag}] {_state_name(enabled)} at "
                f"[{self._settings.base_url}{path}]: {error}",
                known_not_applied=known_not_applied(_THE_WRITE, error)
            ) from error

        undo = FlagUndo(
            flag=flag,
            was_enabled=not enabled,
            environment=self._settings.environment,
            written_at=_when_the_provider_recorded(flag, response)
        )

        self._wait_until_evaluating(flag, enabled, undo)

        return undo

    def changes_since(self, since: datetime, /) -> list[FlagChange]:
        """The flag toggles recorded in the configured environment at or after
        `since`, oldest first.

        Ordered oldest-first although the provider answers newest-first, matching
        every other windowed read in Argus. Callers ask which change was *latest*,
        and having one direction decided here rather than at each call site is
        what stops two of them disagreeing about which end of the list that is.

        The window is applied here rather than by the provider: its events
        endpoint ignores a row limit and answers with the whole log. Correct at
        any size and cheap at the scale this runs at; a real deployment would want
        the provider's own filtering, and this adapter is the one place that
        changes.
        """
        try:
            response = self._admin.get(EVENTS_PATH)
            response.raise_for_status()
            body: dict[str, Any] = response.json()
        except Exception as error:
            raise FlagProviderUnavailable(
                f"could not read flag history at [{self._settings.base_url}{EVENTS_PATH}]: "
                f"{error}"
            ) from error

        toggles = [
            event
            for event in body.get(EVENTS, [])
            if self._is_a_toggle_of_this_environment(event)
            and parse_iso(event[EVENT_CREATED_AT]) >= since
        ]

        return [self._as_flag_change(event) for event in sorted(toggles, key=_recorded_order)]

    def others_changed_since(self, flag: str, since: datetime, /) -> bool | None:
        """Whether anybody but Argus changed `flag` at or after `since`.

        What an undo consults before it writes: a change made after Argus's own
        is somebody's deliberate decision, and putting the flag back would
        overwrite it. A change nobody is recorded for counts as somebody else's -
        a flag left as found can be put back by hand, and an overwritten decision
        cannot.

        `None` where nobody can say: no actor is configured, so the provider
        cannot tell Argus's changes from anybody's, or the history could not be
        read - the difference between putting a change back and overwriting a
        person.
        """
        changes = self._changes_to_attribute(flag, since)

        if changes is None:
            return None

        return any(change.made_by_argus is False for change in changes)

    def _changes_to_attribute(self, flag: str, since: datetime) -> list[FlagChange] | None:
        """`flag`'s changes since `since`, or `None` where nobody can say whose
        any of them was.

        Not raised where the history could not be read: "could not ask" is an
        answer the question's callers have a move for. The reason is logged
        here, where the failure still is, since the answer loses it.
        """
        if not self._settings.actor:
            return None

        try:
            changes = self.changes_since(since)
        except FlagProviderUnavailable:
            logger.warning("flag history could not be read", exc_info=True, extra={"flag": flag})

            return None

        return [change for change in changes if change.flag == flag]

    def _wait_until_evaluating(self, flag: str, enabled: bool, undo: FlagUndo) -> None:
        for attempt in range(_EVALUATION_ATTEMPTS):
            try:
                if (flag in _the_enabled_in(self._frontend._evaluation())) == enabled:
                    return
            except Exception as error:
                raise FlagWriteFailed(
                    f"could not confirm flag [{flag}] is {_state_name(enabled)}: {error}",
                    left_behind=undo
                ) from error

            if attempt + 1 < _EVALUATION_ATTEMPTS:
                self._sleep(_SECONDS_BETWEEN_ATTEMPTS)

        logger.warning("flag accepted but not evaluating", extra={"flag": flag, "enabled": enabled})

        raise FlagWriteFailed(
            f"flag [{flag}] was accepted as {_state_name(enabled)} but still evaluates "
            f"{_state_name(not enabled)}",
            left_behind=undo
        )

    def _feature_path(self, flag: str) -> str:
        return f"/api/admin/projects/{self._settings.project}/features/{flag}"

    def _toggle_path(self, flag: str, enabled: bool) -> str:
        return (
            f"{self._feature_path(flag)}"
            f"/environments/{self._settings.environment}/{_state_name(enabled)}"
        )

    def _enabled_here_in(self, feature: dict[str, Any]) -> bool:
        """Whether the admin read of a flag says it is on in the configured
        environment. Raises where the flag is not in it: a flag never read there
        is not off there."""
        for environment in feature.get(FEATURE_ENVIRONMENTS, []):
            if environment.get(ENVIRONMENT_NAME) == self._settings.environment:
                return bool(environment[ENVIRONMENT_ENABLED])

        raise ValueError(f"the flag is not in environment [{self._settings.environment}]")

    def _is_a_toggle_of_this_environment(self, event: dict[str, Any]) -> bool:
        return (
            event.get(EVENT_TYPE) in (ENABLED_EVENT, DISABLED_EVENT)
            and event.get(EVENT_ENVIRONMENT) == self._settings.environment
            and event.get(EVENT_FLAG) is not None
        )

    def _as_flag_change(self, event: dict[str, Any]) -> FlagChange:
        """One log row in the provider's shape, as the vendor-neutral fact it
        records. Deterministic mapping, never a model: a hallucinated toggle is a
        write to the wrong flag."""
        actor = event.get(EVENT_CREATED_BY)

        return FlagChange(
            flag=event[EVENT_FLAG],
            enabled=event[EVENT_TYPE] == ENABLED_EVENT,
            occurred_at=to_iso(parse_iso(event[EVENT_CREATED_AT])),
            actor=actor,
            made_by_argus=self._was_argus(actor)
        )

    def _was_argus(self, actor: str | None) -> bool | None:
        """Whether the provider's author for a change is the name Argus writes under.

        `None` where no name is configured: Argus and its operators then share a
        credential, and the provider cannot tell their changes apart. A change
        with no recorded author is not Argus's - "the provider did not say" is not
        "Argus did it". The comparison ignores case: the name is seeded in the
        Target Environment's repository and compared in this one, and drift
        between the two would switch the recognition off quietly.
        """
        if not self._settings.actor:
            return None

        return actor is not None and actor.casefold() == self._settings.actor.casefold()


def _a_client(base_url: str,
              token: str,
              transport: httpx2.BaseTransport | None) -> httpx2.Client:
    """One client carrying what every request under one credential shares."""
    return httpx2.Client(
        base_url=base_url,
        headers={AUTHORIZATION_HEADER: token},
        timeout=REQUEST_TIMEOUT_SECONDS,
        transport=transport
    )


def _the_enabled_in(evaluation: dict[str, Any]) -> list[str]:
    """The names of the flags an evaluation answer says are on, in its order.

    A flag that is off is *absent* from the provider's answer rather than
    present and false, so presence is the signal. The `enabled` field is still
    honoured where it appears - a provider that starts reporting disabled
    toggles explicitly would otherwise have every one of them read as on, which
    is the failure that turns a healthy environment into a flag Mitigation
    reverts.
    """
    return [
        toggle[TOGGLE_NAME]
        for toggle in evaluation.get(TOGGLES, [])
        if toggle.get(TOGGLE_ENABLED, True)
    ]


def _when_the_provider_recorded(flag: str, response: httpx2.Response) -> datetime | None:
    """The provider's own time for this write, or `None` where it gave none.

    Read from the response rather than taken from this process's clock, because
    of what it is for: an undo asks the provider which changes came after this
    one, and the provider answers with its own timestamps. Two clocks compared
    against each other are wrong by however much they disagree, and the
    disagreement is invisible - it looks like nobody having touched the flag.

    Absent rather than substituted where the header is missing or unreadable. An
    undo has an answer for a moment it does not know - it says the state could
    not be established - and that is a better answer than a number this process
    made up.
    """
    dated = response.headers.get(DATE_HEADER)

    if not dated:
        logger.warning("provider gave no write time", extra={"flag": flag})
        return None

    try:
        return parsedate_to_datetime(dated)
    except Exception:
        logger.warning("provider gave no write time", extra={"flag": flag, "date": dated})
        return None


def _the_date_on(response: httpx2.Response) -> datetime:
    """The provider's own time on an answer, raising where it gave none or one
    that does not read as a moment.

    Raised rather than left absent, unlike a write's: a write's undo has an
    answer for a moment it does not know, and a plan dated by nothing has
    nothing to ask the history from. Every format RFC 9110 (5.6.7) has a
    recipient accept is read, and every HTTP date is GMT - so the asctime one,
    which names no zone, is UTC rather than this process's zone.
    """
    dated = response.headers.get(DATE_HEADER)

    if not dated:
        raise ValueError("the provider gave no date for the read")

    moment = parsedate_to_datetime(dated)

    return moment if moment.tzinfo is not None else moment.replace(tzinfo=UTC)


def _recorded_order(event: dict[str, Any]) -> int:
    """The provider's own insertion sequence for a log row.

    Ordering on the timestamp instead would leave two changes tied whenever they
    land in the same second, and a flag switched on and straight back off does
    exactly that. A stable sort then keeps the order the provider listed them in,
    which is newest first, so "the latest change" becomes the earliest one and
    the flag gets reverted the wrong way. The event id is the sequence actually
    recorded and it does not tie. It stays inside this adapter: `FlagChange` is
    vendor-neutral and carries no provider id.
    """
    return int(event[EVENT_ID])


def _state_name(enabled: bool) -> str:
    """The provider's own word for a state - and the path segment that sets it,
    which is why one function names both."""
    return "on" if enabled else "off"
