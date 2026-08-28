from __future__ import annotations

from functools import lru_cache

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore", populate_by_name=True)

    database_user: str = Field(default="argus")
    database_password: str = Field(default="argus")
    database_host: str = Field(default="localhost")
    database_port: int = Field(default=5432)

    target_service_url: str = Field(default="http://localhost:8080")

    read_mcp_host: str = Field(default="localhost")
    read_mcp_port: int = Field(default=8090)

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

    mitigate_threshold: float = Field(default=0.75)

    anthropic_api_key: str = Field(default="")

    # Where the Anthropic SDK sends its requests. Empty means the real API.
    # Pointing this at the test double is the *only* thing that selects it:
    # the seam sits below the SDK, so the real adapter, the real
    # `messages.parse` and the real schema transform still run.
    anthropic_base_url: str = Field(default="")

    # How many times the investigation loop may re-read before giving up
    # (spec §10). Each iteration reaches further back, per the widening
    # schedule derived from the log window settings above. At least two: the
    # schedule starts at the initial lookback and ends at the maximum span,
    # which a single iteration cannot do.
    investigation_max_iterations: int = Field(default=3, ge=2)

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
