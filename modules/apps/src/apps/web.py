"""The web process's root: its telemetry, its senders and platforms, then the app.

`python -m apps.web`. What each route does is `web_app`'s; this decides whom
the application hears from - each sender's and each platform's adapter, handed
to it as the port - and serves it.

A `main` of its own rather than uvicorn's command line, because the app is
built here, from this deployment's configuration, and because something has
to start this process's telemetry before the first request and close it after
the last - and the app's lifespan is the wrong place for that: every test that
drives the app through a `TestClient` runs the lifespan, and would install the
SDK for the whole test process and write a run directory each time it did.
"""

from __future__ import annotations

from argparse import ArgumentParser
from typing import Final

import uvicorn
from alert_source.grafana import GrafanaAlerts
from chat_platform.slack import ChatSettings, slack_from
from core import Settings, TelemetrySettings, get_settings
from fastapi import FastAPI
from oncall_source.pagerduty_adapter import pagerduty_from
from oncall_source.pagerduty_settings import PagerDutySettings
from push_source.github import GitHubPushes
from telemetry import start_telemetry
from web_app.app import an_app
from web_app.oncall import OnCallDeliverySettings
from web_app.pushes import PushSettings

# What this process is called in its telemetry, and the directory its runs are
# written under.
_SERVICE: Final = "argus-web"

# The senders of alerts this deployment hears, each at a route of its own,
# `/webhooks/alerts/<name>`, named for the sender. The first is heard at
# `/webhooks/alerts` too, with no name: every sender configured before senders
# had routes of their own posts there.
GRAFANA_ALERTS: Final = "grafana"


def the_app_for(settings: Settings) -> FastAPI:
    """The application, hearing from what this deployment is configured for.

    Each sender's and platform's adapter is built here and nowhere else, and
    handed to the application as its port. The push source holds the secret
    the deployment was given for it, and nothing that reads a repository. The
    on-call and the chat platform are `None` where the deployment has none.
    Building any of them reaches nothing: each asks its vendor only when a
    delivery arrives.
    """
    return an_app(
        alert_sources={GRAFANA_ALERTS: GrafanaAlerts()},
        the_unnamed_senders_name=GRAFANA_ALERTS,
        push_source=GitHubPushes(PushSettings.of(settings).github_webhook_secret),
        oncall_platform=pagerduty_from(
            PagerDutySettings.of(settings),
            webhook_secret=OnCallDeliverySettings.of(settings).pagerduty_webhook_secret
        ),
        chat_platform=slack_from(ChatSettings.of(settings))
    )


def main(argv: list[str] | None = None) -> None:
    """The process: telemetry started, then serve until killed.

    `--host` and `--port` say where to listen, under the names uvicorn's own
    command line gives them.

    Served without uvicorn's own logging config, which would give its loggers
    handlers of their own and stop them propagating to the root, where
    telemetry listens. Without it, uvicorn's records reach the console and
    `logs.jsonl` like every other record.
    """
    parser = ArgumentParser(description="Serves Argus's dashboard and its webhooks.")
    parser.add_argument("--host", default="127.0.0.1", help="the interface to listen on")
    parser.add_argument("--port", type=int, default=8000, help="the port to listen on")
    listening = parser.parse_args(argv)
    settings = get_settings()

    with start_telemetry(TelemetrySettings.of(settings), _SERVICE):
        uvicorn.run(the_app_for(settings), host=listening.host, port=listening.port,
                    log_config=None)


if __name__ == "__main__":
    main()
