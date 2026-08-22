---
name: test-naming-style
description: Use when writing, proposing, or reviewing test code anywhere in this workspace, to name test variables so a reader can tell at a glance which values matter and which are arbitrary.
---

Every literal in a test asks the reader a question: does this value matter, or
is it filler? Answering it means tracing the value through the test to see
whether anything depends on it. That work, repeated per variable, is the
cognitive load these prefixes exist to remove - the name answers the question
before the reader starts tracing.

**`some_` - arbitrary value.** The variable holds a concrete value, but only
its *flow* matters: that it reaches the output, the assertion, the mock. Any
other value of the same type would do.

    some_service = "kuki-service"
    some_alert_name = "HighErrorRate"
    some_high_confidence = a_high_enough_confidence()

**`dont_care_` - required but irrelevant.** The value exists only to satisfy a
signature or a constructor. Nothing asserts on it, and nothing downstream reads
it.

    dont_care_timeout = 30
    dont_care_user_id = "123"

The distinction from `some_`: a `some_` value is expected to show up somewhere
later in the test; a `dont_care_` value never is.

**`a_`/`an_` - builders.** A function that constructs a test object or value is
named as an indefinite article phrase, so call sites read as prose.

    an_incident_state(some_alert, IncidentStatus.INVESTIGATING)
    a_metric_at(some_loud_minute, error_rate=some_anomalous_error_rate)

**No prefix - the value is the point.** This is what the convention buys. An
unprefixed name signals "this value was chosen deliberately, read it": a
threshold, a boundary, an edge case, the specific input the behavior turns on.
Without the prefixes carrying the arbitrary cases, this signal doesn't exist
and every value looks equally significant.

    expected_statuses = ["investigating", "mitigating"]
    empty_log = []

**No magic values - derive them.** A literal whose meaning comes from its
relationship to another value must be computed from that value, never written
out. The arithmetic is the explanation.

    # bad - why 39? why 41?
    too_narrow_max_window = 39
    some_line_inside_the_window = "2026-08-20T11:41:00Z"

    # good - the expression says which side of which boundary it sits on
    too_narrow_max_window = some_lookback_minutes + some_lookahead_minutes - 1
    some_line_inside_the_window = a_log_line_at(some_alert_time - timedelta(minutes=1))

This holds for every kind of literal, not just numbers - timestamps, ids,
status strings, paths. A value that must match something else (a config
default, a fixture entry, another variable in the test) is derived from it or
imported from it, so the two cannot drift apart silently. A boundary test in
particular is worthless if a reader can't tell from the code which boundary it
is testing.

**The prefixes are for test bodies only.** They exist to tell a reader of a
test which values that test cares about - a question that only arises inside a
test. Local variables inside a helper, builder or fixture take ordinary names,
because there is no test being read there to be arbitrary *with respect to*.

    def an_alert_time() -> datetime:
        minutes_ago = random.randint(...)   # not `some_minutes_ago`
        ...

Parameters of builders are likewise named plainly (`minute`, `error_rate`,
`lookback_minutes`); the `some_`/`dont_care_` judgement is made by the caller,
at the call site, where it is visible.

Applies to proposed test code as much as to written code - the user reads a
proposal before pasting it, and the prefixes are what make it skimmable.
