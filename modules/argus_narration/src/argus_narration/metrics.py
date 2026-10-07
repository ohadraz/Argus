"""One minute of the service's metrics, as a row on the page.

Nothing here judges the incident. `elevated` is the mark a reader's eye lands
on and nothing more - the judgement of which minutes departed from the baseline
was made by `argus_core.anomaly` while the investigation ran, and is already in
the narration as the onset.
"""

from __future__ import annotations

from argus_core.models import MetricBucket
from pydantic import BaseModel

from argus_narration.clock import a_minute

# The error rate at which a minute is marked on the page. The same figure the
# Target Service's own console reddens a row at, and copied deliberately rather
# than shared: the two screens sit side by side during a demo, and one that
# marked a different set of minutes than the other would make a reader
# translate between them. Presentation only - nothing decides anything on it,
# and the judgement of which minutes departed from the baseline belongs to
# `argus_core.anomaly`, which made it while the investigation ran.
_ELEVATED_ERROR_RATE = 0.05

# Where a byte count stops being read in megabytes. A working set is quoted in
# whichever unit keeps it to three or four digits, which is how every dashboard
# a reader has seen quotes it - `1946 MB` beside a `2.0 GB` limit is the same
# fact said in two units, and the comparison is the only reason both are shown.
_BYTES_PER_MEGABYTE = 1024**2
_BYTES_PER_GIGABYTE = 1024**3


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
    # The slowest one request in a hundred. Shown beside the other two rather
    # than left off as a detail, because it is the only column an incident
    # reaching a few requests in a hundred appears in - a table without it
    # would show a reader four flat series and no reason anybody was paged.
    p99_ms: int
    request_volume: int
    # What the service's memory was doing, already in the units a person reads
    # it in. A byte count is the wrong thing to put in a table a reader scans
    # for a climb: nine digits changing in their middle is a column nobody can
    # see a trend in.
    memory: str
    # What the service's CPU was doing, in cores and against the capacity it had.
    # Rendered rather than reported for the reason memory is, and with one thing
    # memory does not need: usage clamps at capacity, so a saturated minute is two
    # equal figures - and a reader scanning a column of pairs for equality is being
    # asked to do arithmetic the column can do for them.
    cpu: str
    # The minute's value of the series the paging rule evaluates, where the
    # window was read for a rule that watches one - on an incident in what the
    # service answers, the only column that moved. The value alone: which way
    # the rule calls worse is the same on every minute and is not a reading. To
    # three figures, since a backend's average arrives with sixteen. `None` where
    # the minute carries none, which is not a reading of zero.
    rule_reading: str | None = None
    elevated: bool


def a_bucket_row(bucket: MetricBucket) -> BucketRow:
    """One minute of metrics, with the mark the reader's eye lands on."""
    return BucketRow(
        bucket_id=bucket.bucket_id,
        when=a_minute(bucket.bucket_id),
        error_rate=bucket.error_rate,
        p50_ms=bucket.p50_ms,
        p95_ms=bucket.p95_ms,
        p99_ms=bucket.p99_ms,
        request_volume=bucket.request_volume,
        memory=_memory_said(bucket.memory_used_bytes, bucket.memory_limit_bytes),
        cpu=_cpu_said(bucket.cpu_used_cores, bucket.cpu_limit_cores),
        rule_reading=(
            f"{bucket.rule_reading.value:.3g}" if bucket.rule_reading is not None else None
        ),
        elevated=bucket.error_rate >= _ELEVATED_ERROR_RATE
    )


def _memory_said(used_bytes: int, limit_bytes: int | None) -> str:
    """What the service was using, against what it was allowed.

    The limit is said beside the usage rather than left to be looked up: a
    working set means nothing on its own, and the whole question a reader asks
    of this column is how close to the ceiling it has got. A deployment with no
    limit configured has no ceiling to be close to, and the usage is said
    alone - not against a zero that would read as a service already over.
    """
    if limit_bytes is None:
        return _a_size(used_bytes)

    return f"{_a_size(used_bytes)} of {_a_size(limit_bytes)}"


def _cpu_said(used_cores: float, limit_cores: float | None) -> str:
    """What the service was using, against what it had between its replicas.

    The capacity is said beside the usage for the reason the memory limit is: a
    figure in cores means nothing alone, and 0.8 is a quiet afternoon across three
    replicas and an emergency on one. A deployment with no limit configured has no
    ceiling to be near, and the usage is said alone - not against a zero that would
    read as a service already over.

    Saturation is named rather than left to be inferred, which is the one thing
    this says and the memory column does not. Usage cannot exceed capacity, so a
    saturated minute is two equal figures and nothing more - and a reader scanning
    a column of pairs for equality is doing work the column can do for them. It is
    also the whole signal of the one incident this series exists to show.
    """
    if limit_cores is None:
        return f"{_cores(used_cores)} cores"

    said = f"{_cores(used_cores)} of {_cores(limit_cores)} cores"

    if used_cores < limit_cores:
        return said

    return f"{said}, saturated"


def _cores(cores: float) -> str:
    """A core count at the precision a reader can act on.

    One decimal, which is the precision a utilisation figure is quoted at
    everywhere a reader has seen one. Three would be the measurement's own
    precision and nobody's question: the difference between 0.774 and 0.776 cores
    is not a difference anybody scans a column for.
    """
    return f"{cores:.1f}"


def _a_size(byte_count: int) -> str:
    """A byte count in the unit it is ordinarily quoted in."""
    if byte_count >= _BYTES_PER_GIGABYTE:
        return f"{byte_count / _BYTES_PER_GIGABYTE:.1f} GB"

    return f"{round(byte_count / _BYTES_PER_MEGABYTE)} MB"
