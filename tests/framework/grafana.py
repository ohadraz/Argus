"""The words of Grafana's webhook Argus's adapter never reads.

Whatever in these suites writes a notification as Grafana does spells the
words the adapter reads by importing them from `alert_source.grafana`, and
these - what Grafana sends beside them - from here, once. The receiver a
notification went through, when an alert ended, the labels and annotations its
group shares, where Grafana is served, the webhook's version, and Grafana's
word for an alert still firing, which the adapter knows only as "not resolved".
"""

from __future__ import annotations

from typing import Final

RECEIVER: Final = "receiver"
ENDS_AT: Final = "endsAt"
GROUP_LABELS: Final = "groupLabels"
COMMON_LABELS: Final = "commonLabels"
COMMON_ANNOTATIONS: Final = "commonAnnotations"
EXTERNAL_URL: Final = "externalURL"
VERSION: Final = "version"

# What Grafana writes in `endsAt` while an alert has not ended.
NOT_ENDED: Final = "0001-01-01T00:00:00Z"

# What Grafana calls an alert whose rule is firing.
FIRING: Final = "firing"
