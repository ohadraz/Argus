"""The text a later incident is compared against.

Assembled, not written. Its only job is to be matched against, and the alert's
own words beside what the investigation concluded embed to very nearly where a
composed sentence would - at no cost, with no failure mode, and reproducibly.
A description a model wrote would be one this module could not produce twice.

Two halves, for two kinds of match. The alert's wording finds an incident a
later alert names the same way; the conclusion and the observations find one
that looked the same under a different name, which is the case a small closed
set of alert names cannot show and a real service produces constantly.
"""

from __future__ import annotations

from argus_core.models import Alert, Hypothesis


def what_it_looked_like(alert: Alert, hypothesis: Hypothesis | None) -> str:
    """One text, carrying everything this incident can be recognised by.

    A hypothesis is optional because an escalation may never have named a cause,
    and that incident is still worth finding: its record says which actions were
    taken and did not help, which never depended on a cause being named.

    Every piece is omitted rather than emptied when it is missing. A join that
    kept the absent ones would hand the embedder a separator with nothing on
    either side, and hand a reader something they would report as a bug.
    """
    said = [_the_alerts_own_words(alert)]

    if hypothesis is not None:
        said.append(hypothesis.summary)
        said.extend(cited.claim for cited in hypothesis.supporting_evidence)

    return "\n".join(line for line in said if line)


def _the_alerts_own_words(alert: Alert) -> str:
    """What the monitoring called it, as the monitoring put it.

    The name and the service together, because a name alone is ambiguous across
    services and a later search narrows by service anyway - a description that
    omitted it would match a differently-named incident on another service more
    readily than the same one here.

    `summary` is optional on a real alert and is left out when it is absent,
    rather than rendered as an empty clause after the colon.
    """
    named = f"{alert.alert_name} on {alert.service}"

    return f"{named}: {alert.summary}" if alert.summary else named
