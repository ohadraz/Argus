"""Which Argus incidents an on-call platform's page is about.

Asked when a person resolves the page, not when the alert arrived. Grafana
pages the platform and Argus at the same moment, so at intake the platform's
page may not exist yet; by the time somebody resolves it, it does. It is found
through the keys its senders stamped on it - which a merge carries over to the
page merged into - among the incidents going on while the page was open, and
by the platform's own id where an earlier match already linked it.

A decision about incidents rather than about a delivery, so it is the record's
and not the web application's: any process that hears from the platform asks
it the same way. Nothing here knows which platform answered, or reads it - the
page's keys arrive as values, and when it was open arrives as a callable,
which installs no on-call port here.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence

from core.models import NOTIFICATION_KEY, ON_CALL_INCIDENT, Lifespan

from incident_record.incident_names import IncidentNames


def incidents_a_page_is_about(names: IncidentNames,
                              page: str,
                              keys: Sequence[str],
                              the_pages_life: Callable[[], Lifespan]) -> list[str]:
    """The Argus incidents the platform's page `page` is about, each once.

    Those an earlier read already linked to it, and those holding one of its
    `keys` that were going on while it was open. A key alone names no
    incident: every firing of an alert group pages under the group's one key,
    so an alert that stopped and started again leaves an older incident
    holding the key of a page opened long after it ended - and resolving that
    one would leave the incident the page was about still open.

    `the_pages_life` is read at most once, and only where some incident holds
    one of the keys. Most pages are about incidents Argus never opened, and a
    platform that cannot say when its page was open must not fail a resolution
    the link alone settled. Where it is read and fails, the failure is raised:
    a person's word lost to a blip is worse than one asked for again.
    """
    linked = names.incidents_known_as(ON_CALL_INCIDENT, [page])
    keyed = names.incidents_known_as(NOTIFICATION_KEY, keys)

    if keyed:
        open_while = the_pages_life()
        keyed = [incident for incident in keyed if incident.lifespan.overlaps(open_while)]

    return list(dict.fromkeys(incident.id for incident in [*linked, *keyed]))
