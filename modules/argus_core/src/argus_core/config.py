from __future__ import annotations

from functools import lru_cache
from typing import Final

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# The longest single wait inside a walk: Mitigation standing by for the service
# to answer an action. Named here because two settings are stated in terms of
# it - the wait itself, and the lease that has to outlast it.
_VERIFICATION_TIMEOUT_SECONDS: Final = 180.0

# How many of those waits a claim survives before another worker may take the
# run back. More than one, because a walk can verify more than one action; small
# enough that a worker killed mid-walk does not leave its incident sitting for
# an hour.
_LEASES_PER_LONGEST_WAIT: Final = 4


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore", populate_by_name=True)

    database_user: str = Field(default="argus")
    database_password: str = Field(default="argus")
    database_host: str = Field(default="localhost")
    database_port: int = Field(default=5432)

    target_service_url: str = Field(default="http://localhost:8080")

    read_mcp_host: str = Field(default="localhost")
    read_mcp_port: int = Field(default=8090)

    # The feature-flag provider, read side. This credential can evaluate flags
    # and cannot change one, which is what makes `argus-read-mcp` incapable of
    # mutation rather than merely disinclined (spec §13, §14). The admin
    # credential belongs to `argus-write-mcp` alone and is not read here.
    unleash_base_url: str = Field(default="http://localhost:4242")
    unleash_frontend_token: str = Field(
        default="default:production.argus-demo-frontend-token"
    )
    # Which project and environment a flag change addresses. Read-side calls
    # need neither - the evaluation credential is already scoped to one
    # environment - but the admin API names both in its path.
    unleash_project: str = Field(default="default")
    unleash_environment: str = Field(default="production")
    # The credential that can change a flag. `argus-write-mcp` holds it and
    # `argus-read-mcp` is issued none: the tier boundary is enforced by which
    # process possesses which secret, not only by which code paths exist
    # (spec §13, §14). Empty by default so a misconfigured write server fails
    # loudly rather than silently authenticating as nobody.
    unleash_admin_token: str = Field(default="")
    # The name the provider attributes Argus's own flag writes to - the username
    # on the credential above, seeded by the Target Environment's compose file
    # and matched here exactly. It is what lets a change Argus made be told from
    # a change a human made, so that a later look at "what recently changed"
    # does not offer Argus its own action as a cause. Empty switches that
    # filtering off, which is the honest setting for a deployment where Argus
    # and its operators share one credential and the distinction cannot be made.
    unleash_actor: str = Field(default="Argus")

    write_mcp_host: str = Field(default="localhost")
    write_mcp_port: int = Field(default=8092)

    log_initial_lookback_minutes: int = Field(default=30)
    log_initial_lookahead_minutes: int = Field(default=10)
    # Ceiling on any log window. Widening is how a reasoning caller reaches an 
    # onset that predates its window; this stops that widening from degenerating 
    # into a full-log dump.
    log_max_window_minutes: int = Field(default=180)

    # Metrics are pre-aggregated - one minute is four numbers - so the summary
    # is fetched at one fixed, wide span rather than iterating. Expected to be
    # wider than the log ceiling: seeing an onset Argus cannot afford to read
    # logs for is a useful answer ("onset predates my log budget"), where not
    # seeing it at all is a silent miss.
    metrics_window_minutes: int = Field(default=360)

    # How far back Mitigation looks for the flag change an incident is about.
    # Far shorter than `change_lookback_minutes`, and deliberately so: that one
    # asks "how far back may a cause plausibly lie" for an investigation, where
    # this asks "what did someone just change" about an incident happening now.
    # Widening it makes an ambiguous environment - two flags changed, so no
    # action - the common case rather than the exception.
    flag_change_lookback_minutes: int = Field(default=60, gt=0)

    # How long Mitigation waits for the service to answer an action before
    # calling the hypothesis refuted. Expiry is a verdict, not an error: the
    # action was taken and did not visibly help in the time allowed, which is
    # what refuted means. Long enough to cover at least one whole metric minute
    # plus the lag before the service's behaviour changes.
    mitigation_verification_timeout_seconds: float = Field(
        default=_VERIFICATION_TIMEOUT_SECONDS, gt=0.0
    )

    # How long a worker waits before asking the queue again, having found it
    # empty. The wait a real alert pays before anything starts on it, so it is
    # short - and it is only paid when there is nothing to do, since a worker
    # that found work looks again immediately.
    run_poll_interval_seconds: float = Field(default=2.0, gt=0.0)

    # How long a claim holds a run before another worker may take it back. A
    # worker renews this while it walks, so it bounds how long a *stopped*
    # worker's run sits unwalked - not how long a run may take.
    #
    # Comfortably longer than the longest single wait inside a walk, which is
    # Mitigation's verification: a lease that expired while a worker sat
    # waiting for a service to recover would hand the same incident to a second
    # worker at exactly the moment the first was about to answer.
    run_lease_seconds: float = Field(
        default=_VERIFICATION_TIMEOUT_SECONDS * _LEASES_PER_LONGEST_WAIT, gt=0.0
    )

    anthropic_api_key: str = Field(default="")

    # Where the Anthropic SDK sends its requests. Empty means the real API.
    # Pointing this at the test double is the *only* thing that selects it:
    # the seam sits below the SDK, so the real adapter, the real
    # `messages.parse` and the real schema transform still run.
    anthropic_base_url: str = Field(default="")

    # The credential the payment provider is read with. Empty by default, and
    # empty means the source reports that it could not answer: a postmortem
    # resting on money nobody can vouch for is worse than one saying the figure
    # is missing, and a default credential would be one nobody chose.
    stripe_api_key: str = Field(default="")

    # Where the Stripe SDK sends its requests. Empty means the real API.
    # Pointing this at the shop's own Stripe-shaped endpoint is the only thing
    # that selects it: the seam sits below the SDK, so the vendor's request
    # building, paging and object model all still run.
    stripe_base_url: str = Field(default="")

    # The credential the on-call provider is read with. Empty by default, for
    # the reason the payment credential is: a response time nobody can vouch
    # for is worse than one the document says it could not obtain, and a
    # default credential would be one nobody chose.
    pagerduty_api_key: str = Field(default="")

    # Where the PagerDuty SDK sends its requests. Empty means the real API.
    # Pointing this at the Target Service's PagerDuty-shaped endpoints is the
    # only thing that selects them: the seam sits below the SDK, so the
    # vendor's request building and error vocabulary still run.
    pagerduty_base_url: str = Field(default="")

    # Whether the on-call provider's certificate is checked. True everywhere
    # that matters: PagerDuty's own certificate is real, and so is the one a
    # platform issues a deployed stand-in. False only against the demo running
    # on this machine, whose TLS listener mints itself a certificate nobody has
    # any reason to trust - and which exists at all because the vendor's SDK
    # refuses a base URL that is not `https://`.
    pagerduty_verify_tls: bool = Field(default=True)

    # Where the day's exchange rates are read from. Frankfurter publishes the
    # European Central Bank's reference rates, needs no account and no key, and
    # answers a whole table in one request - so unlike every other provider
    # here it has a working default rather than an empty one, and a deployment
    # that configures nothing still converts.
    exchange_rate_base_url: str = Field(default="https://api.frankfurter.dev")

    # The currency a postmortem states its loss estimate in, and the base every
    # rate is quoted against. A shop paid in several currencies has no total
    # until one of them is chosen, and choosing is a business decision rather
    # than an arithmetic one - so it is configured, and the document discloses
    # what it converted at to get there.
    reporting_currency: str = Field(default="usd")

    # What bounds one investigation once the model, rather than a schedule,
    # decides what to read. Three of them, because they fail differently and
    # none implies the others: a model reading three-hour windows is cheap in
    # calls and ruinous in tokens, one looping on a narrow window is the
    # reverse, and one frugal in both can still leave a human waiting past the
    # point the answer was worth having.
    #
    # How many retrievals the model may make in total, across every turn.
    # Counted in calls rather than turns, since a model may ask for several
    # channels at once. Roughly four times what one round of the schedule this
    # replaces would read, because the point of the change is that a model
    # which needs a fourth look may take one.
    investigation_max_tool_calls: int = Field(default=12, ge=1)

    # The ceiling on what one investigation may cost, both directions summed.
    # Input dominates: the API is stateless, so every turn resends the whole
    # transcript, and a conversation's cost grows with the square of its
    # length. Set from the measured spend of the loop this replaces at its
    # maximum iterations, with room for the extra turns a tool loop takes -
    # the worst case is meant to start no worse than what it replaces.
    investigation_max_tokens: int = Field(default=150_000, ge=1)

    # How long an investigation may run before it is called off, whatever it
    # has or has not spent. This is the bound that answers to the human
    # waiting on the incident rather than to the accountant.
    investigation_max_seconds: float = Field(default=300.0, gt=0.0)

    # How many times one incident may be investigated. A round after the first
    # is bought by a refuted attempt, not by a wider window: Argus changed
    # production and the service did not answer, which is evidence the model has
    # never seen and cannot infer from any amount of reading. That is why this
    # is its own budget rather than whatever the widening schedule has left -
    # the schedule bounds what there is to *read*, and a hard incident spends it
    # all before answering, exactly when a second opinion is worth most.
    investigation_max_rounds: int = Field(default=3, ge=1)

    # How many of one verdict's explanations the walk will try, best first.
    # A ceiling rather than a quota: a verdict naming fewer is left alone, and
    # a verdict naming more keeps its most confident. How long an answer the
    # model gives is its own business, but what that answer costs is not - each
    # candidate is a real change to production and a wait for the service to
    # answer, and the graph's traversal budget is derived from this number.
    # One is the walk Argus had before it could walk: best explanation, then a
    # human.
    investigation_max_candidates: int = Field(default=4, ge=1)

    # How far a minute has to sit from the service's own calm baseline before
    # it counts as the incident starting. Measured in the baseline's own
    # spread, not in error-rate points, so one number works for a service that
    # idles at 0.5% errors and one that idles at 8% - an absolute threshold
    # would be wrong for both.
    # Must be positive: at zero every minute counts as anomalous, including
    # the calm ones the baseline is derived from.
    anomaly_deviations_from_baseline: float = Field(default=3.0, gt=0.0)

    # How many consecutive minutes have to stay departed before the first of
    # them counts as the incident starting. An incident is a state, so it
    # holds; a lone departed minute is sampling noise that had already
    # recovered by the next one. Two rather than more because the onset is
    # what every retrieval window is anchored on: a longer requirement buys
    # little against noise and starts missing brief real incidents.
    anomaly_persistence_minutes: int = Field(default=2, ge=1)

    # Where deploy history is read from. The demo Target Service stands in for
    # a real Argo CD server, so the default points at it - but the adapter
    # makes the request a real Argo CD answers, and pointing these at one is
    # the only change needed.
    argocd_base_url: str = Field(default="http://localhost:8080")
    # A template, so the demo's stand-in and a real Argo CD's
    # `/api/v1/applications/{application}` are the same setting - only the
    # value differs. A path carrying no placeholder is formatted to itself.
    argocd_application_path: str = Field(default="/argocd/{application}")
    # Empty means no credential is sent at all, rather than an invented one -
    # the stand-in needs none, and a real Argo CD issues these to operators.
    argocd_auth_token: str = Field(default="")

    # How far back to look for changes. Wide on purpose, and far wider than
    # any log window: a cause precedes its symptoms by an unbounded lag - a
    # flag toggled at 09:00 that only breaks under the 14:00 peak - and
    # changes are sparse, so a day of them is a handful of rows where a day of
    # logs is millions of lines.
    change_lookback_minutes: int = Field(default=1440, gt=0)

    @property
    def database_url(self) -> str:
        return (
            f"postgresql://{self.database_user}:{self.database_password}"
            f"@{self.database_host}:{self.database_port}/argus"
        )

    @property
    def read_mcp_url(self) -> str:
        return f"http://{self.read_mcp_host}:{self.read_mcp_port}"

    @property
    def write_mcp_url(self) -> str:
        return f"http://{self.write_mcp_host}:{self.write_mcp_port}"

    @model_validator(mode="after")
    def _windows_must_be_consistent(self) -> Settings:
        """Rejects a configuration whose windows contradict each other.

        Two relationships have to hold for retrieval to make sense, and
        neither is enforced by the individual fields:

        - The log ceiling must admit the window the server derives itself.
          Otherwise `get_log_lines` hands out a 40-minute derived window while
          refusing a 40-minute explicit one - the derived path does no
          clamping, so nothing else would catch it.
        - The metrics span must exceed that ceiling. Metrics exist to locate an
          onset the log budget may not reach; a metrics window no wider than
          the logs' can only ever confirm what the logs already showed.
        - The change lookback must exceed it too, for the same reason. The
          change channel exists to surface a cause the log window cannot
          reach; no wider than the ceiling, it can only repeat what the logs
          already carried.
        """
        derived_log_window_minutes = (
            self.log_initial_lookback_minutes + self.log_initial_lookahead_minutes
        )

        if self.log_max_window_minutes < derived_log_window_minutes:
            raise ValueError(
                f"log_max_window_minutes ({self.log_max_window_minutes}) must be at least the "
                f"derived log window of {derived_log_window_minutes} minutes "
                f"(log_initial_lookback_minutes + log_initial_lookahead_minutes)"
            )

        if self.metrics_window_minutes <= self.log_max_window_minutes:
            raise ValueError(
                f"metrics_window_minutes ({self.metrics_window_minutes}) must be wider than "
                f"log_max_window_minutes ({self.log_max_window_minutes})"
            )

        if self.change_lookback_minutes <= self.log_max_window_minutes:
            raise ValueError(
                f"change_lookback_minutes ({self.change_lookback_minutes}) must be wider than "
                f"log_max_window_minutes ({self.log_max_window_minutes})"
            )

        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()
