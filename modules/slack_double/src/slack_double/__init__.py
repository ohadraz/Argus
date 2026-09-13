"""A record of what Argus would have said in Slack, with no workspace involved.

The second external party Argus stands in for, after the Anthropic API, and on
the same terms: a real HTTP server the SDK is pointed at by base URL, dev-only,
excluded from test discovery, and kept honest by a contract test against the
real workspace. The suites stay free and keyless; nothing in the Communicator
branches on whether Slack is real.
"""

from slack_double.server import DEFAULT_BASE_URL, DEFAULT_PORT, Posted, Seed, app

__all__ = [
    "DEFAULT_BASE_URL",
    "DEFAULT_PORT",
    "Posted",
    "Seed",
    "app",
]
