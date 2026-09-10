"""One minute of the service's metrics, as a row on the page.

Nothing here judges the incident. `elevated` is the mark a reader's eye lands
on and nothing more - the judgement of which minutes departed from the baseline
was made by `argus_core.anomaly` while the investigation ran, and is already in
the narration as the onset.
"""

from __future__ import annotations

from argus_core.models.metrics import MetricBucket
from pydantic import BaseModel

from argus_web.views.clock import a_minute

# The error rate at which a minute is marked on the page. The same figure the
# Target Service's own console reddens a row at, and copied deliberately rather
# than shared: the two screens sit side by side during a demo, and one that
# marked a different set of minutes than the other would make a reader
# translate between them. Presentation only - nothing decides anything on it,
# and the judgement of which minutes departed from the baseline belongs to
# `argus_core.anomaly`, which made it while the investigation ran.
_ELEVATED_ERROR_RATE = 0.05


class BucketRow(BaseModel):
    """One minute of metrics as the page shows it.

    `elevated` is presentation and nothing else: it is the mark the reader's
    eye lands on, not a judgement about the incident. The judgement was made by
    `argus_core.anomaly` while the investigation ran, and is in the narration
    already as the onset.
    """

    bucket_id: str
    # The same minute a person reads off a clock. `bucket_id` stays as it is
    # because it is the minute's identity - what the row is keyed and linked by
    # - and `when` is that identity said out loud.
    when: str
    error_rate: float
    p50_ms: int
    p95_ms: int
    request_volume: int
    elevated: bool


def a_bucket_row(bucket: MetricBucket) -> BucketRow:
    """One minute of metrics, with the mark the reader's eye lands on."""
    return BucketRow(
        bucket_id=bucket.bucket_id,
        when=a_minute(bucket.bucket_id),
        error_rate=bucket.error_rate,
        p50_ms=bucket.p50_ms,
        p95_ms=bucket.p95_ms,
        request_volume=bucket.request_volume,
        elevated=bucket.error_rate >= _ELEVATED_ERROR_RATE,
    )
