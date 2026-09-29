from __future__ import annotations

import json
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

import pytest
from agent_investigator import BRIEF, Findings, investigate, investigator_tools
from agent_investigator.budget import Bound, Budget, InvestigationSettings
from argus_core import get_settings, new_id, parse_iso
from argus_core.llm import build_llm_client
from argus_core.models import (
    Alert,
    ChangeEvent,
    ChangeKind,
    FailureMode,
    Hypothesis,
    MetricBucket,
    Ownership,
    RetrievalChannel,
    ServiceDependency,
    ToolDefinition,
    Transcript,
    Turn,
)
from argus_testkit.assertions import Assertion, all_of, at_least
from argus_testkit.scenario import Scenario

from tests.framework.assertions import the_cause_was_identified_as
from tests.framework.investigating import the_configured_thresholds
from tests.framework.pooling import Configuration, a_digest_of, the_samples_taken

# An eval judges the model's judgement, not Argus's plumbing, so it talks to the
# real API and spends tokens every run. Each run is now a whole investigation -
# the model chooses which channel to read, over what window, and when it has
# seen enough - which is the thing worth measuring: the loop hands it three
# tools and no sequence, so what it does with them *is* the behaviour.
#
# The evidence below is pinned in this file rather than pulled from the Target
# Service on purpose: if the fixture can drift, a change in the score no longer
# tells you anything about the model. The retrieval seams serve it as the real
# ones would - a window in, only what falls inside it out - so a cause outside
# the window the model asked for is genuinely not in front of it, and widening
# is a decision it has to make rather than one the fixture makes for it.
needs_the_real_api = pytest.mark.skipif(
    not get_settings().anthropic_api_key,
    reason="no ANTHROPIC_API_KEY: an eval has nothing to measure without the real model",
)

# The model samples, so one call is a draw and not a verdict. Each case is run
# this many times and scored as a rate.
#
# Ten is a floor rather than a target. At five, a 95% interval spans some forty
# points either side and distinguishes nothing short of total failure; at ten it
# is nearer twenty-five, which catches a regression. So this is not what to cut
# when a run costs too much - five cases at ten samples is the fifty
# investigations a full run bills for, and the thing to run less of is *cases*.
# `-k` selects them, each batch pools with the last, and one case is ten walks.
RUNS_PER_CASE = 10

# What a single batch is allowed to conclude: that something broke, and nothing
# finer. A rate from ten samples is compared against the bar below and never
# written into it - a threshold fitted to one batch claims a precision ten
# samples do not have. `pooling` holds the depths at which a pool may be acted
# on and re-derived from, and every sample a run takes is appended there so that
# reaching those depths is a matter of running again rather than paying once.
#
# The case names below are what a sample is filed under. They are spelled out
# rather than taken from the test's own name, because a pool outlives a rename.
A_BATCH_DETECTS_A_REGRESSION_AND_DERIVES_NOTHING = True

THIS_EVAL = "investigator"
CASE_THE_FLAG_TOGGLE = "flag-toggled-on-is-identified"
CASE_NO_CHANGE_EVENT = "no-change-event-stays-undetermined"
CASE_THE_BAD_DEPLOYMENT = "deploy-before-latency-is-identified"
CASE_THE_UNRELATED_CHANGE = "unrelated-change-is-not-blamed"
CASE_THE_LOWER_BOUND = "lower-bound-onset-is-read-past"
CASE_THE_UPSTREAM_FAILURE = "upstream-dependency-failure-is-identified"
CASE_THE_INTERNAL_FAILURE = "internal-dependency-failure-is-told-from-upstream"
CASE_THE_MOVED_PORT = "config-induced-failure-is-told-from-a-bad-deployment"
CASE_THE_REWRITTEN_SUM = "bad-deployment-is-told-from-a-config-change"
CASE_THE_SATURATION = "demand-saturation-is-identified"
CASE_THE_LEAK = "resource-leak-is-told-from-demand-saturation"
CASE_THE_FLAPPING_AUTOSCALER = "autoscaling-pathology-is-told-from-demand-saturation"
CASE_THE_STOPPED_ROLLOUT = "in-flight-compatibility-break-is-told-from-a-bad-deployment"

# **Derived from 50 pooled samples of each case per configuration**, recorded in
# `results/investigator.tsv` and read from it rather than restated: five batches
# of ten under each arm that has been tried. They replace an 8-of-10 bar
# inherited from the single-shot prompt this loop replaced, which measured a
# model that was handed the evidence rather than one that chooses its own reads.
#
# A bar is set where a batch of ten passes when nothing has changed and fails
# when the rate really drops - so it sits below the pooled rate, not at it. The
# five cases below are held 50 of 50 by every model and effort tried, which is
# what makes them regression tests rather than comparisons; 9 is the first figure
# a single lapse survives while two do not. Re-measure after any change to
# `BRIEF`, to a tool description, or to the budget, and do not re-derive from a
# batch: 10 samples distinguish nothing short of total failure.
# That re-measure is owed twice over, and the second time is the larger of the two.
# The deployment channel moved `BRIEF` and the tool list, so every figure below
# describes the configuration digested as `33a135e3fc06`. The autoscaling mode then
# moved `BRIEF` again - it now tells the Investigator to read `cpu_limit_cores`
# before naming saturation or a leak - which is a change aimed squarely at the
# capacity pair two of these bars score. So the digest named above no longer
# describes what any of this is measured against, and the pair's figures are the
# least trustworthy in the file rather than the most. They are kept as the last
# thing that was true rather than reset, and the pool separates the arms.
MUST_IDENTIFY_THE_FLAG_TOGGLE = 9  # 50/50 on every arm
MUST_STAY_UNDETERMINED = 9  # 50/50 on every arm
MUST_IDENTIFY_THE_BAD_DEPLOYMENT = 9  # 50/50 on every arm
MUST_READ_PAST_THE_LOWER_BOUND = 9  # 50/50 on every arm
MUST_IDENTIFY_THE_UPSTREAM_FAILURE = 9  # 50/50 on every arm
# The one case no arm is reliably right about, and so the only one that tells two
# configurations apart: 41 of 50 on the configured model, 38 of 50 on the tier
# above it. A bar at 8 would fail one run in five with nothing wrong; 7 is what
# 82% supports. Raising it means improving the model's judgement, not the number.
MUST_NOT_BLAME_THE_UNRELATED_CHANGE = 7  # 41/50 on the configured model
# The one bar in this file that is not derived from anything, because the case it
# scores did not exist when the pools were taken and cannot be measured before it
# does. It is written at its siblings' figure as a starting point and is not
# evidence of anything until the first pooled run either confirms it or moves it -
# so a failure here reads as "unmeasured", not as a regression. It is also the
# hardest claim in the suite: the evidence for the two dependency causes is
# identical by construction, and only the register separates them.
MUST_IDENTIFY_THE_INTERNAL_FAILURE = 9  # UNMEASURED - no pooled samples yet
# The second matched pair, and unmeasured for the same reason. Both members
# stage a deployment before a latency departure with identical metrics,
# identical log lines and a summary that says only that a deployment happened;
# the single variable is what the commit changed. A model that reads a
# deployment and guesses which kind it was gets one of these right half the
# time, which is what the pair exists to catch.
MUST_IDENTIFY_THE_MOVED_PORT = 9  # UNMEASURED - no pooled samples yet
MUST_IDENTIFY_THE_REWRITTEN_SUM = 9  # UNMEASURED - no pooled samples yet
# The third matched pair, and unmeasured for the reason the others are. Both
# members stage a service that got slower with no change behind it, identical log
# lines and a heap that never spilled; the single variable is whether the
# consumption moved *with* the traffic. A model that reads a latency climb and
# reaches for the nearest resource story gets one of these right, and the wrong
# one costs a walk its mitigation - a restart buys a saturated shop a moment
# before the load returns it, and capacity added to a leaking one is capacity
# that leaks too.
MUST_IDENTIFY_THE_SATURATION = 9  # UNMEASURED - no pooled samples yet
MUST_IDENTIFY_THE_LEAK = 9  # UNMEASURED - no pooled samples yet
# The third member of the capacity family, unmeasured for its siblings' reason and
# with less standing than either: the evidence its twin reads is a subset of this
# one's, so a model that never looks at the capacity series passes the twin and
# fails this - and the paragraph above means neither figure has been measured
# against the prompt that now tells it to look.
MUST_IDENTIFY_THE_FLAPPING_AUTOSCALER = 9  # UNMEASURED - no pooled samples yet
# The pair whose evidence agrees most completely of any in this suite, and the
# only one where a wrong answer still reaches the right action - so what this
# figure measures is the honesty of the record rather than the fitness of the
# mitigation. Unmeasured for its siblings' reason and owed the same pass: the
# standing brief now tells the model to read the rollout before blaming the
# revision a deployment carried, and no figure here was measured against it.
MUST_IDENTIFY_THE_STOPPED_ROLLOUT = 9  # UNMEASURED - no pooled samples yet

# How sure a model may sound about a cause the evidence does not carry.
#
# The two "nothing explains this" fixtures and the upstream one are a matched
# pair: same alert, same buckets, same empty change list, and only the log text
# differs. So a cause reached from the metric shape alone is reached from
# evidence all of them share - a guess by construction, however well it reads.
#
# Scored as calibration rather than as silence, because silence is not what the
# brief asks for. A model that says "possibly upstream, and I could not confirm
# it" at 0.55 is the brief working; the same cause at 0.9 is the fabrication
# these two cases were written to catch, and the walk will act on it - a named
# cause is enough to start a mitigation, whatever the number beside it.
A_CAUSE_THE_EVIDENCE_DOES_NOT_CARRY_MAY_NOT_EXCEED = 0.6

# The budget every case is measured under, pinned here for the same reason the
# evidence is: a rate that moved with a deployment's `.env` would say nothing
# about the model. These are the configured defaults as they stand, restated so
# that changing them is a change to this file and shows up in review beside the
# thresholds it would invalidate.
MAX_TOOL_CALLS = 12
# 200,000 and not 150,000, which is what stood here while
# `investigation_max_tokens` said 200,000 - so every score on record was taken
# under a tighter bound than production gives the model. The restatement exists
# to make a changed bound show up in review beside the thresholds it
# invalidates, and it drifted anyway; re-syncing it invalidates them again, in
# the lenient direction.
MAX_TOKENS = 200_000
MAX_SECONDS = 300.0

ONSET = datetime(2026, 3, 2, 10, 5, tzinfo=UTC)
# Which bucket the incident actually starts in. The four fixtures that open
# calm depart here - error rate or latency - three minutes into their window.
ONSET_OFFSET_MINUTES = 1

CALM_ERROR_RATE = 0.01
SPIKED_ERROR_RATE = 0.38
CALM_P50_MS = 45
CALM_P95_MS = 220
CALM_P99_MS = 380
CALM_MEMORY_BYTES = 440 * 1024**2
MEMORY_LIMIT_BYTES = 2 * 1024**3
DONT_CARE_STARTED_AT = 1_756_000_000.0
SLOW_P50_MS = 900
SLOW_P95_MS = 4800
SLOW_P99_MS = 6200

# What the shop serves and what it has to serve it with when nothing is wrong.
# Named rather than spelled at each bucket, because the saturation pair is the
# first thing here to vary either of them and a literal that varies is a literal
# somebody will read as arbitrary.
CALM_REQUEST_VOLUME = 1200
CALM_CPU_CORES = 0.77
CPU_LIMIT_CORES = 3.0

# The surge, as the volume the shop reports rather than as a rate somebody chose:
# four times the traffic against capacity sized for one - which is what makes the
# deployment too small rather than broken.
SURGED_REQUEST_VOLUME = CALM_REQUEST_VOLUME * 4

# Usage pinned at the ceiling, because a service cannot use more CPU than it has.
# That is the whole signature: the gauge stops climbing while the latency does
# not, where a number growing past its own limit is not a thing a real gauge
# does.
SATURATED_CPU_CORES = CPU_LIMIT_CORES
# The ceiling during the minutes a controller had already added replicas. Twice the
# declared size, which is what makes the shop briefly comfortable at the same
# traffic - and it is the *second* value of a series every other fixture here holds
# at one, which is the whole of what separates a capacity that will not settle from
# one that was outgrown.
A_DOUBLED_CEILING = CPU_LIMIT_CORES * 2

# Where a heap that has been filling for an hour sits: close enough to the limit
# to be the story, and not spilled - nothing has failed here, which is what keeps
# the pair's two members the same shape.
LEAKING_MEMORY_BYTES = int(MEMORY_LIMIT_BYTES * 0.94)

A_SUCCESS = "INFO checkout: request succeeded"
A_SLOW_SUCCESS = "INFO checkout: request succeeded in 4820ms"
A_FLAG_TOGGLED_ON = "WARN checkout: feature flag 'checkout-v2' toggled from 'off' to 'on'"
A_FAILURE_IN_THE_FLAGGED_PATH = (
    "ERROR checkout: request failed - unhandled exception in checkout-v2 path"
)
A_FAILURE_FROM_UPSTREAM = "ERROR checkout: request failed - upstream returned 503"
# A failure that blames nobody. The two "nothing here explains this" cases need
# evidence that genuinely explains nothing, and an upstream 503 stopped being
# that the day `UPSTREAM_DEPENDENCY_FAILURE` became a cause Argus can name and
# act on: a model reading those lines now identifies a real failure mode, and is
# right to. Measured - twenty runs out of twenty named it.
A_FAILURE_THAT_NAMES_NOTHING = "ERROR checkout: request failed"

# The register entry that makes the upstream case answerable. The log lines say a
# dependency returned 503; they cannot say whose it is, and a host name is not
# evidence of ownership - so without this the case asks for a cause the model is
# told to reach only from a register it was handed empty.
#
# A payment provider, because that is the shop's one genuinely external call, and
# `THIRD_PARTY` verbatim rather than a word of the test's own: `is_ours` tests for
# the word that means ours, so an invented spelling would read as not-ours by
# accident and pass for the wrong reason.
A_PAYMENT_PROVIDER_ANOTHER_COMPANY_RUNS = ServiceDependency(
    name="acquirer-gateway",
    purpose="authorises the card on the account page",
    host="api.acquirer.example.com",
    owner="Acquirer Inc.",
    ownership=Ownership.THIRD_PARTY
)

# Its pair, and the entry the whole discrimination turns on. Everything a model
# can read about the failure is identical between the two cases; only this
# differs, and only this decides whether Argus restarts something or hands the
# incident to a person.
#
# Deliberately the same shape of dependency as its pair - a service on the
# request path, failing the same way - so that nothing but `ownership` separates
# them. A more obviously internal-sounding name would let a model reach the right
# answer from the name, which is the reading this exists to rule out.
A_PRICING_SERVICE_THE_ORGANISATION_RUNS = ServiceDependency(
    name="io-pricing",
    purpose="prices the basket on the account page",
    host="io-pricing.internal",
    owner="Payments Platform",
    ownership=Ownership.INTERNAL
)

A_PRICING_REWRITE = "checkout: replace the cached pricing lookup with a per-item query"

# The matched pair's two revisions, and what each one shipped. The summaries
# are what the deploy adapter actually writes - a revision and the directory
# the application syncs from - rather than prose describing the change, because
# a real deployment does not come with a description and the cases either side
# of this pair are generous in a way production is not.
THE_REVISION_THAT_MOVED_A_PORT = "0d8e826"
THE_REVISION_THAT_REWROTE_A_SUM = "5e07d73"

# What the deployment channel answers for each, as the read tier renders it.
# One changes a value in the file the deployment carried and no source at all;
# the other changes the function on the request path. Nothing else about the
# two incidents differs.
WHAT_THE_MOVED_PORT_SHIPPED = [
    f"Deployment of revision {THE_REVISION_THAT_MOVED_A_PORT} to io-shop, "
    f"compared against 544cef3 - the revision deployed before it.",
    "modified deploy/values-production.yaml",
    "  @@ -24,4 +24,4 @@ cache:",
    "     host: cache.io-shop.svc.cluster.local",
    "  -  port: 6379",
    "  +  port: 6380"
]
WHAT_THE_REWRITTEN_SUM_SHIPPED = [
    f"Deployment of revision {THE_REVISION_THAT_REWROTE_A_SUM} to io-shop, "
    f"compared against 70dbcfd - the revision deployed before it.",
    "modified src/io_shop/spend_summary.py",
    "  @@ -18,7 +18,13 @@ def lifetime_total(shopper, purchases):",
    "  -    return shopper.summary.lifetime_total",
    "  +    return sum(",
    "  +        purchase.amount for purchase in purchases_of(shopper)",
    "  +    )"
]
A_LOG_LEVEL_BUMP = "checkout: raise the structured-log level from info to debug"

# The deploy that explains nothing, named once so the fixture that stages it and
# the assertion that refuses it cannot come to mean different deploys.
AN_UNRELATED_DEPLOY = "4d1b90c"

# What that deploy shipped. One value in the file the deployment carried, no
# source file at all, and a value nothing on the request path reads - so it
# cannot produce an error-rate spike, and the diff is what says so.
WHAT_THE_LOG_LEVEL_BUMP_SHIPPED = [
    f"Deployment of revision {AN_UNRELATED_DEPLOY} to io-shop, compared against "
    f"c77ab41 - the revision deployed before it.",
    "modified deploy/values-production.yaml",
    "  @@ -9,3 +9,3 @@ logging:",
    "  -  level: info",
    "  +  level: debug"
]

# Where the toggle sits in the widening fixture: far enough before the onset
# that the default log window - which reaches back `log_initial_lookback_minutes`
# - cannot contain it, and well inside the ceiling on a widened one, so reading
# it is affordable rather than merely permitted.
TOGGLED_LONG_BEFORE_THE_WINDOW_OPENS = -45

# Where the unrelated deploy sits: far enough before the onset that the calm
# minutes between the two are visible in the metrics span, so the model can
# read the gap rather than having to be told the change was harmless.
DEPLOYED_LONG_BEFORE_THE_ONSET = -40

# The revision this scenario's deployment is rolling out, and the one the
# replicas that have not updated are still on. Real commits in the Target
# Service, as the two above are.
THE_REVISION_THAT_RESHAPED_A_CACHE_ENTRY = "696c33a"
THE_REVISION_STILL_SERVING = "5470c1a"

# What the rollout channel answers. Prose rather than a shape, because that is
# what the channel returns: a replica count, two revisions, whether the update
# is paused, and when the state began.
A_ROLLOUT_STOPPED_HALF_WAY = [
    f"Deployment of io-shop has not converged: 3 of 6 replicas are running "
    f"revision [{THE_REVISION_THAT_RESHAPED_A_CACHE_ENTRY}], and 3 are still "
    f"running revision [{THE_REVISION_STILL_SERVING}].",
    "Its rolling update is paused, so the platform is not converging it on its "
    "own.",
    "The revision it is converging on was deployed at 2026-08-20T11:05:00Z, "
    "which is when the replicas first differed."
]
A_CONVERGED_DEPLOYMENT = [
    "Deployment of io-shop has converged: all 3 replicas are running revision "
    "[a3f9c21], deployed at 2026-08-20T11:05:00Z."
]

# What the deployment carried. A stored shape that changed, with no read path
# kept for the old one - which is the missing expand step of an expand-contract
# migration, and the only thing in the diff that says so.
WHAT_THE_RESHAPED_ENTRY_SHIPPED = [
    f"Deployment of revision {THE_REVISION_THAT_RESHAPED_A_CACHE_ENTRY} to "
    f"io-shop, compared against {THE_REVISION_STILL_SERVING} - the revision "
    f"deployed before it.",
    "modified src/io_shop/summary_cache.py",
    "  @@ -38,7 +38,10 @@ def read_summary(entry):",
    "  -    return Cents(int(entry))",
    "  +    amount, items = entry.split('/')",
    "  +    return Summary(Cents(int(amount)), int(items))"
]

A_FAILURE_READING_A_CACHE_ENTRY = (
    "ERROR checkout: summary cache entry could not be read - ValueError: "
    "summary cache entry '2400/8' is not a figure in cents"
)


@pytest.mark.eval
@needs_the_real_api
def test_a_flag_toggled_on_before_the_error_spike_is_identified() -> None:
    some_incident = an_incident_where_a_flag_was_toggled_on()

    Scenario() \
        .given(
            some_incident
        ) \
        .when(
            lambda: _the_real_model_investigates_repeatedly(some_incident)
        ) \
        .then(
            _scored(
                CASE_THE_FLAG_TOGGLE,
                MUST_IDENTIFY_THE_FLAG_TOGGLE,
                _a_run_where(the_cause_was_identified_as(FailureMode.FEATURE_FLAG_TOGGLE)),
            )
        )


@pytest.mark.eval
@needs_the_real_api
def test_an_error_spike_with_no_change_event_is_left_undetermined() -> None:
    # The honest-failure path, measured. Nothing in this evidence explains the
    # spike, and a model that names a cause anyway is the failure mode the
    # whole "undetermined is a valid answer" instruction exists to prevent.
    # It is also the case a tool loop makes easier to fail: a model that can
    # keep asking has more chances to talk itself into something.
    some_incident = an_incident_with_no_change_event()

    Scenario() \
        .given(
            some_incident
        ) \
        .when(
            lambda: _the_real_model_investigates_repeatedly(some_incident)
        ) \
        .then(
            _scored(CASE_NO_CHANGE_EVENT, MUST_STAY_UNDETERMINED,
                    _a_run_where_nothing_was_claimed_confidently())
        )


@pytest.mark.eval
@needs_the_real_api
def test_a_dependency_failing_outside_the_service_is_identified() -> None:
    # A cause with no change event behind it, which is the shape that made the
    # two "stays undetermined" cases wrong: they were built when an unexplained
    # spike meant an unknowable one. It is knowable - the log lines name the
    # dependency, and the service's own latency, traffic and memory never move -
    # and a model that says so has read the evidence rather than guessed at it.
    some_incident = an_incident_where_an_upstream_dependency_failed()

    Scenario()         .given(
            some_incident
        )         .when(
            lambda: _the_real_model_investigates_repeatedly(some_incident)
        )         .then(
            _scored(
                CASE_THE_UPSTREAM_FAILURE,
                MUST_IDENTIFY_THE_UPSTREAM_FAILURE,
                _a_run_where(
                    all_of(
                        the_cause_was_identified_as(
                            FailureMode.UPSTREAM_DEPENDENCY_FAILURE
                        ),
                        # Null, and asserted: the field belongs to the cause that
                        # is acted on, and a name here would be a service Argus
                        # cannot reach offered as one it can.
                        _the_faulting_service_was_named_as(None)
                    )
                ),
            )
        )


@pytest.mark.eval
@needs_the_real_api
def test_a_dependency_failing_inside_the_organisation_is_told_from_one_outside() -> None:
    # The pair, and the only case here whose single variable is the register.
    # Same alert, same buckets, same log lines, same empty change list as the
    # case above - a dependency returning 503 while this service's own latency,
    # traffic and memory never move. Everything a model could read from the
    # telemetry is identical, so the two causes are separable by exactly one
    # fact: whether the register says the failing dependency is the
    # organisation's own.
    #
    # That is the discrimination the whole internal-dependency cause rests on,
    # and it decides what happens next rather than only what is written down: a
    # service of the organisation's own gets restarted, and somebody else's gets
    # escalated to a human. A model that reads a 503 and guesses gets one of
    # those right half the time.
    #
    # `faulting_service` is asserted here and nowhere else in the suite, because
    # this is the one cause that carries it. It is what the restart is aimed at.
    some_incident = an_incident_where_an_internal_dependency_failed()

    Scenario() \
        .given(
            some_incident
        ) \
        .when(
            lambda: _the_real_model_investigates_repeatedly(some_incident)
        ) \
        .then(
            _scored(
                CASE_THE_INTERNAL_FAILURE,
                MUST_IDENTIFY_THE_INTERNAL_FAILURE,
                _a_run_where(
                    all_of(
                        the_cause_was_identified_as(
                            FailureMode.INTERNAL_DEPENDENCY_FAILURE
                        ),
                        _the_faulting_service_was_named_as(
                            A_PRICING_SERVICE_THE_ORGANISATION_RUNS.name
                        )
                    )
                ),
            )
        )


@pytest.mark.eval
@needs_the_real_api
def test_a_deploy_before_a_latency_departure_is_identified() -> None:
    # What the third channel is for, and now a decision rather than a gift.
    # The deploy appears in no log line and lands before any log window the
    # model can afford, so this cause is reachable only by choosing to read the
    # change channel at all - and the deploy says what it changed, never that
    # it was slow. Reading a per-item query as a latency regression is the
    # judgement being measured; reaching for the channel that holds it is the
    # judgement the loop added.
    some_incident = an_incident_where_a_deploy_slowed_the_service()

    Scenario() \
        .given(
            some_incident
        ) \
        .when(
            lambda: _the_real_model_investigates_repeatedly(some_incident)
        ) \
        .then(
            _scored(
                CASE_THE_BAD_DEPLOYMENT,
                MUST_IDENTIFY_THE_BAD_DEPLOYMENT,
                _a_run_where(the_cause_was_identified_as(FailureMode.BAD_DEPLOYMENT)),
            )
        )


@pytest.mark.eval
@needs_the_real_api
def test_a_deployment_that_changed_only_configuration_is_told_from_bad_code()\
        -> None:
    # The second matched pair in this suite, and the only one whose single
    # variable is a diff. Same alert, same buckets, same log lines, same one
    # deployment six minutes before the onset, and a summary that says only that
    # a deployment happened and which directory it synced from - which is all a
    # deployment record carries. Everything readable from the telemetry is
    # identical to the twin below, so the two causes are separable by exactly
    # one fact: whether the commit touched source code or the values it shipped
    # with.
    #
    # It decides what is left owed rather than only what is written down. A
    # rollback answers both, and afterwards one team has a values file to fix
    # and the other has a function - so an incident filed under the wrong one
    # sends the work to the wrong people.
    #
    # The answer is asserted and the reasoning is not. A model can reach the
    # right cause by an argument this fixture does not stage, and scoring the
    # argument would measure how it writes rather than what it concluded.
    some_incident = an_incident_where_a_deployment_moved_a_port()

    Scenario() \
        .given(
            some_incident
        ) \
        .when(
            lambda: _the_real_model_investigates_repeatedly(some_incident)
        ) \
        .then(
            _scored(
                CASE_THE_MOVED_PORT,
                MUST_IDENTIFY_THE_MOVED_PORT,
                _a_run_where(
                    the_cause_was_identified_as(
                        FailureMode.CONFIG_INDUCED_FAILURE
                    )
                )
            )
        )


@pytest.mark.eval
@needs_the_real_api
def test_a_deployment_that_changed_source_code_is_told_from_configuration()\
        -> None:
    # The twin. Its value is entirely in being scored beside the case above: a
    # model that answers `bad-deployment` to every deployment passes this one
    # and fails that one, and a model that answers `config-induced-failure` to
    # every deployment does the reverse. Only a model that reads the diff passes
    # both, which is the claim the channel was added to support.
    some_incident = an_incident_where_a_deployment_rewrote_a_sum()

    Scenario() \
        .given(
            some_incident
        ) \
        .when(
            lambda: _the_real_model_investigates_repeatedly(some_incident)
        ) \
        .then(
            _scored(
                CASE_THE_REWRITTEN_SUM,
                MUST_IDENTIFY_THE_REWRITTEN_SUM,
                _a_run_where(
                    the_cause_was_identified_as(FailureMode.BAD_DEPLOYMENT)
                )
            )
        )


@pytest.mark.eval
@needs_the_real_api
def test_a_service_that_outgrew_its_capacity_is_told_from_one_that_is_leaking()\
        -> None:
    # The third matched pair, and the only one whose variable is a resource.
    # Same alert, same latency climb, same log lines, and nothing changed in
    # either: no deployment, no toggle, no dependency at fault. What differs is
    # which reading moved with the other - here the traffic quadruples, CPU pins
    # against a ceiling it cannot exceed, and the heap never stirs.
    #
    # It decides what Argus does next and not only what is written down. A
    # saturated deployment is answered by adding capacity and a leak by
    # reclaiming what accumulated, so an incident filed under the wrong half of
    # resource exhaustion gets the one mitigation that cannot work: a restart
    # buys a saturated shop the minutes until the load returns it.
    some_incident = an_incident_where_demand_outgrew_the_capacity()

    Scenario() \
        .given(
            some_incident
        ) \
        .when(
            lambda: _the_real_model_investigates_repeatedly(some_incident)
        ) \
        .then(
            _scored(
                CASE_THE_SATURATION,
                MUST_IDENTIFY_THE_SATURATION,
                _a_run_where(
                    the_cause_was_identified_as(FailureMode.DEMAND_SATURATION)
                )
            )
        )


@pytest.mark.eval
@needs_the_real_api
def test_a_heap_that_filled_while_the_traffic_stood_still_is_told_from_saturation()\
        -> None:
    # The twin, and its value is entirely in being scored beside the case above:
    # a model that answers `resource-leak` to every resource story passes this
    # one and fails that one, and a model that answers `demand-saturation` to
    # both does the reverse. Only a model that reads whether the consumption
    # tracked the traffic passes both.
    #
    # The traffic is flat to the minute and the heap climbs to within a few
    # percent of its limit. CPU stays where it was, which is the reading that
    # rules the other half out: a shop using a quarter of its cores is not a shop
    # that has run out of room to serve.
    some_incident = an_incident_where_a_heap_filled_without_the_traffic()

    Scenario() \
        .given(
            some_incident
        ) \
        .when(
            lambda: _the_real_model_investigates_repeatedly(some_incident)
        ) \
        .then(
            _scored(
                CASE_THE_LEAK,
                MUST_IDENTIFY_THE_LEAK,
                _a_run_where(the_cause_was_identified_as(FailureMode.RESOURCE_LEAK))
            )
        )


@pytest.mark.eval
@needs_the_real_api
def test_a_capacity_that_will_not_settle_is_told_from_one_that_was_outgrown()\
        -> None:
    # The pair this scenario was built around, and the hardest separation in the
    # suite: its twin's evidence is a subset of this one's. At the bottom of every
    # cycle the alert, the quantiles, the traffic and the change channels all read
    # as demand saturation, and the only thing that says otherwise is one series
    # taking two values.
    #
    # Its twin is `test_a_service_that_outgrew_its_capacity_is_told_from_one_that_is_leaking`,
    # unchanged by this mode's arrival, which is half the claim: a fourth resource
    # story must not make the model hedge on the three that were already right.
    some_incident = an_incident_where_the_capacity_would_not_settle()

    Scenario() \
        .given(
            some_incident
        ) \
        .when(
            lambda: _the_real_model_investigates_repeatedly(some_incident)
        ) \
        .then(
            _scored(
                CASE_THE_FLAPPING_AUTOSCALER,
                MUST_IDENTIFY_THE_FLAPPING_AUTOSCALER,
                _a_run_where(
                    the_cause_was_identified_as(FailureMode.AUTOSCALING_PATHOLOGY)
                )
            )
        )


@pytest.mark.eval
@needs_the_real_api
def test_a_rollout_that_did_not_converge_is_told_from_a_bad_deployment() -> None:
    # The pair with the least to separate it and the most riding on the answer.
    # Its twin is the deploy-before-a-latency-climb case, and both reach the same
    # rollback - so unlike every other pair here, getting this wrong does not
    # produce a wrong action. It produces a correct action and a false record: a
    # revision named as the fault, and a fix filed against code with no defect in
    # it.
    #
    # Which is also why this is the only place the claim lives. The e2e case
    # cannot assert it, because a wrong reading would have ended the incident too.
    some_incident = an_incident_where_a_rollout_stopped_half_way()

    Scenario() \
        .given(
            some_incident
        ) \
        .when(
            lambda: _the_real_model_investigates_repeatedly(some_incident)
        ) \
        .then(
            _scored(
                CASE_THE_STOPPED_ROLLOUT,
                MUST_IDENTIFY_THE_STOPPED_ROLLOUT,
                _a_run_where(
                    the_cause_was_identified_as(
                        FailureMode.IN_FLIGHT_COMPATIBILITY_BREAK
                    )
                )
            )
        )


@pytest.mark.eval
@needs_the_real_api
def test_a_change_that_does_not_explain_the_symptoms_is_not_blamed() -> None:
    # The cost of the third channel, measured. This is the undetermined case
    # above with one deploy added and nothing else touched, so a drop here
    # says precisely one thing: handing the model something that *looks* like
    # an actor made it name a cause it had no evidence for. What marks this
    # deploy as not the cause is in the evidence: forty calm minutes sit
    # between it and the onset, so a model that reads the metrics can see the
    # service was fine long after it landed.
    some_incident = an_incident_with_an_unrelated_change()

    Scenario() \
        .given(
            some_incident
        ) \
        .when(
            lambda: _the_real_model_investigates_repeatedly(some_incident)
        ) \
        .then(
            _scored(
                CASE_THE_UNRELATED_CHANGE,
                MUST_NOT_BLAME_THE_UNRELATED_CHANGE,
                all_of(
                    _a_run_where_nothing_was_claimed_confidently(),
                    _the_deploy_was_not_blamed()
                ),
            )
        )


@pytest.mark.eval
@needs_the_real_api
def test_an_onset_that_is_only_a_lower_bound_is_read_past() -> None:
    # The judgement the widening schedule used to make for the model, now the
    # model's own. Every minute retrieved is inside the incident, so the onset
    # is a lower bound and the opening message says so; the toggle that caused
    # it happened before the window opens, and the default log window cannot
    # reach it. A model that reads the default window and answers has answered
    # from evidence that never contained the cause.
    #
    # What is scored is the reach, not the verdict. Whether it then names the
    # toggle is the flag-toggle case above; what is measured here is that it
    # asked for a window earlier than the one it was given for free - the one
    # move no amount of confidence would prompt, since it cannot miss what it
    # was never shown.
    some_incident = an_incident_underway_before_the_window_opens()

    Scenario() \
        .given(
            some_incident
        ) \
        .when(
            lambda: _the_real_model_investigates_repeatedly(some_incident)
        ) \
        .then(
            _scored(
                CASE_THE_LOWER_BOUND,
                MUST_READ_PAST_THE_LOWER_BOUND,
                _a_run_where_the_logs_were_read_before(_the_default_log_window_opens_at()),
            )
        )


@dataclass(frozen=True)
class Incident:
    """One pinned incident, as the six retrieval channels would serve it.

    The alert and the metrics are what the loop reads before the model's first
    turn. The log lines and the changes are what is *available* to be read -
    which is not the same as what the model will see, and the difference is
    most of what these evals measure.

    `dependencies` is what the register would answer, and it is evidence rather
    than scenery: two of the causes Argus can name differ only in who owns the
    failing dependency, so which of them is correct for a set of log lines is
    decided here and nowhere else. Empty for every case that stages none.

    `what_each_deployment_changed` is the same kind of fact for the other pair
    that arrives identically - a deployment that shipped bad code and one that
    shipped a broken configuration value - keyed by the revision a case would be
    asked about. Empty for every case where no deployment's contents decide
    anything.
    """

    alert: Alert
    buckets: list[MetricBucket]
    log_lines: list[str]
    changes: list[ChangeEvent]
    dependencies: list[ServiceDependency]
    what_each_deployment_changed: dict[str, list[str]] = field(default_factory=dict)
    # How far the fixture records this incident's deployment as having got. The
    # same kind of fact as the two above, for the third pair that arrives
    # identically: a revision that is wrong and a revision that reached half the
    # fleet are one deploy at the onset either way, and only this separates them.
    # Empty for every case where no rollout decides anything.
    rollout: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class Run:
    """One whole investigation, and what it cost.

    The budget is asked afterwards rather than inferred from the summary: an
    investigation that ran out says so in prose meant for a human, and a score
    that depended on that wording would fail the day it is reworded.
    """

    findings: Findings
    ran_out_of: list[Bound]


def an_incident_where_a_flag_was_toggled_on() -> Incident:
    return _an_incident(
        alert=an_error_rate_alert(),
        buckets=_a_calm_stretch_then_a_spike(),
        log_lines=[
            a_log_line_at(-1, A_SUCCESS),
            a_log_line_at(0, A_FLAG_TOGGLED_ON),
            a_log_line_at(1, A_FAILURE_IN_THE_FLAGGED_PATH),
            a_log_line_at(2, A_FAILURE_IN_THE_FLAGGED_PATH)
        ],
        changes=[]
    )


def an_incident_with_no_change_event() -> Incident:
    # Same spike, same buckets, one thing missing: anything that changed. The
    # two fixtures share `_a_calm_stretch_then_a_spike` so they cannot drift
    # apart in some second way - if they did, the eval would be measuring the
    # fixture rather than the model.
    return _an_incident(
        alert=an_error_rate_alert(),
        buckets=_a_calm_stretch_then_a_spike(),
        log_lines=_a_spike_nothing_explains(),
        changes=[]
    )


def an_incident_where_an_upstream_dependency_failed() -> Incident:
    # The evidence the two cases above used to be handed while being asked for
    # "no cause". Nothing changed in this service and nothing needs to have:
    # the failure arrived through a dependency, the log lines say which, and
    # the service's own latency and traffic never move. Naming that is right,
    # and this is where it is now asked for rather than penalised.
    #
    # The register is part of that evidence and was not, which made this case
    # unanswerable the day the two dependency causes were told apart: upstream
    # is reachable only once the register says another company owns the failing
    # dependency, and a 503 in a log line is not evidence of who owns anything.
    # Handed an empty register, the correct reading of these lines is
    # internal-dependency-failure or nothing at all.
    return _an_incident(
        alert=an_error_rate_alert(),
        buckets=_a_calm_stretch_then_a_spike(),
        log_lines=_an_upstream_outage(),
        changes=[],
        dependencies=[A_PAYMENT_PROVIDER_ANOTHER_COMPANY_RUNS]
    )


def an_incident_where_an_internal_dependency_failed() -> Incident:
    # Deliberately the fixture above with one field changed, the way
    # `an_incident_with_an_unrelated_change` is `an_incident_with_no_change_event`
    # plus a deploy. Same alert, same buckets, same log lines, same empty change
    # list; the register says the failing dependency is the organisation's own.
    #
    # That single difference is the only thing either score may be attributed to,
    # which is what makes the pair a measurement of the discrimination rather
    # than of two unrelated readings. If the two fixtures ever diverge in
    # anything else, they stop measuring it.
    return _an_incident(
        alert=an_error_rate_alert(),
        buckets=_a_calm_stretch_then_a_spike(),
        log_lines=_an_upstream_outage(),
        changes=[],
        dependencies=[A_PRICING_SERVICE_THE_ORGANISATION_RUNS]
    )


def an_incident_with_an_unrelated_change() -> Incident:
    # Deliberately `an_incident_with_no_change_event` plus one deploy, sharing
    # its alert, its buckets and its log lines. The single difference between
    # the two fixtures is the difference the two scores are allowed to
    # attribute anything to.
    #
    # The deploy sits forty minutes before the onset, with forty calm minutes
    # recorded between the two. That is what makes it unrelated in the
    # evidence rather than by assumption: an earlier fixture put it two
    # minutes back, where the only thing marking it innocent was knowing a
    # log-level bump is inert - a claim about the diff's semantics that is
    # nowhere in what the model was handed, and not reliably true either.
    return _an_incident(
        alert=an_error_rate_alert(),
        buckets=_a_calm_stretch_then_a_spike(),
        log_lines=_a_spike_nothing_explains(),
        changes=[
            a_deploy_at(
                DEPLOYED_LONG_BEFORE_THE_ONSET, AN_UNRELATED_DEPLOY, A_LOG_LEVEL_BUMP
            )
        ],
        # Its diff, beside the forty calm minutes rather than instead of them.
        # The gap is still what makes the deploy unrelated in the evidence; this
        # is the second, independent reason - a log level in a values file, no
        # source at all, and nothing a request passes through. A model that
        # declines to blame it can now say why from something it read, where
        # before it could only decline to blame a deploy it knew nothing about.
        what_each_deployment_changed={
            AN_UNRELATED_DEPLOY: WHAT_THE_LOG_LEVEL_BUMP_SHIPPED
        }
    )


def an_incident_where_a_deploy_slowed_the_service() -> Incident:
    return _an_incident(
        alert=a_latency_alert(),
        buckets=_a_calm_stretch_then_a_latency_departure(),
        log_lines=[
            a_log_line_at(-1, A_SUCCESS),
            a_log_line_at(1, A_SLOW_SUCCESS),
            a_log_line_at(2, A_SLOW_SUCCESS)
        ],
        # Six minutes before the onset and in no log line at all: the change
        # channel is the only place this exists, whatever window the model
        # reads the logs over.
        changes=[a_deploy_at(-6, "a3f9c21", A_PRICING_REWRITE)],
        # Given its own diff, so that a model reaching for the deployment
        # channel here learns what this one shipped rather than that the
        # fixture records nothing about it.
        what_each_deployment_changed={"a3f9c21": WHAT_THE_REWRITTEN_SUM_SHIPPED},
        # Converged, and that is what makes this the twin of the stopped rollout
        # rather than merely another deployment: the single variable between the
        # two is this answer, so a model that never asks passes one and fails the
        # other whichever way it guesses.
        rollout=A_CONVERGED_DEPLOYMENT
    )


def an_incident_where_a_deployment_moved_a_port() -> Incident:
    """A deployment whose commit changed one configuration value.

    Half of a matched pair. Everything a model can read apart from the diff is
    the same here as in the twin below: the same alert, the same latency
    departure, the same log lines, and a deployment six minutes before the
    onset whose summary says only that it happened and where it synced from.
    """
    return _an_incident(
        alert=a_latency_alert(),
        buckets=_a_calm_stretch_then_a_latency_departure(),
        log_lines=[
            a_log_line_at(-1, A_SUCCESS),
            a_log_line_at(1, A_SLOW_SUCCESS),
            a_log_line_at(2, A_SLOW_SUCCESS)
        ],
        changes=[
            a_deploy_at(
                -6,
                THE_REVISION_THAT_MOVED_A_PORT,
                _as_a_deploy_is_actually_summarised(
                    THE_REVISION_THAT_MOVED_A_PORT
                )
            )
        ],
        what_each_deployment_changed={
            THE_REVISION_THAT_MOVED_A_PORT: WHAT_THE_MOVED_PORT_SHIPPED
        }
    )


def an_incident_where_a_deployment_rewrote_a_sum() -> Incident:
    """A deployment whose commit changed the code on the request path.

    The other half. Identical to the case above in every channel but one, so a
    verdict that differs between the two differs on the diff and on nothing
    else - and a verdict that does not differ was reached without reading it.
    """
    return _an_incident(
        alert=a_latency_alert(),
        buckets=_a_calm_stretch_then_a_latency_departure(),
        log_lines=[
            a_log_line_at(-1, A_SUCCESS),
            a_log_line_at(1, A_SLOW_SUCCESS),
            a_log_line_at(2, A_SLOW_SUCCESS)
        ],
        changes=[
            a_deploy_at(
                -6,
                THE_REVISION_THAT_REWROTE_A_SUM,
                _as_a_deploy_is_actually_summarised(
                    THE_REVISION_THAT_REWROTE_A_SUM
                )
            )
        ],
        what_each_deployment_changed={
            THE_REVISION_THAT_REWROTE_A_SUM: WHAT_THE_REWRITTEN_SUM_SHIPPED
        }
    )


def an_incident_where_a_rollout_stopped_half_way() -> Incident:
    """A deployment that landed and did not finish arriving.

    The near-miss of `an_incident_where_a_deploy_slowed_the_service`, and the
    hardest pair in the suite to separate for a reason none of the others share:
    both are answered by the same rollback, so a model that gets this wrong takes
    the right action and writes a false record - a revision named as the fault
    and a fix filed against code with no defect in it.

    Everything a model can read is a neighbour's. The metrics are the flag
    toggle's exactly - an error rate that steps with every quantile flat - so the
    flag history has to be read before that shape is believed, and it is empty.
    The change channel is a bad deployment's - one deploy before the onset - so
    the rollout has to be read before the revision is blamed. The diff shows a
    stored shape that changed with no read path kept for the old one, which is
    the fault in the process rather than in either revision.

    The single variable against its twin is the rollout channel's answer.
    """
    return _an_incident(
        alert=an_error_rate_alert(),
        buckets=_a_calm_stretch_then_a_spike(),
        log_lines=[
            a_log_line_at(-1, A_SUCCESS),
            a_log_line_at(1, A_FAILURE_READING_A_CACHE_ENTRY),
            a_log_line_at(2, A_FAILURE_READING_A_CACHE_ENTRY)
        ],
        changes=[
            a_deploy_at(
                -6,
                THE_REVISION_THAT_RESHAPED_A_CACHE_ENTRY,
                _as_a_deploy_is_actually_summarised(
                    THE_REVISION_THAT_RESHAPED_A_CACHE_ENTRY
                )
            )
        ],
        what_each_deployment_changed={
            THE_REVISION_THAT_RESHAPED_A_CACHE_ENTRY: WHAT_THE_RESHAPED_ENTRY_SHIPPED
        },
        rollout=A_ROLLOUT_STOPPED_HALF_WAY
    )


def an_incident_where_demand_outgrew_the_capacity() -> Incident:
    """Load that grew past the size somebody deployed for.

    Half of a matched pair. Nothing changed and nothing is at fault: the shop is
    running the code it was reviewed with, serving four times the traffic it was
    sized for, and every quantile has climbed with the gauge pinned against a
    ceiling it cannot exceed.

    No change events and no register, because the absence is part of the evidence
    - the three causes a model might otherwise reach for are each ruled out by
    something it can read rather than by something it is told.
    """
    return _an_incident(
        alert=a_latency_alert(),
        buckets=_a_calm_stretch_then_a_surge(),
        log_lines=_a_service_that_only_got_slower(),
        changes=[]
    )


def an_incident_where_a_heap_filled_without_the_traffic() -> Incident:
    """The other half: consumption that climbed on its own.

    Identical to the case above in every channel but the readings - the same
    alert, the same slowing, the same log lines, the same empty change list - so
    a verdict that differs between the two differs on whether the consumption
    moved with the traffic, and a verdict that does not differ was reached
    without looking.

    CPU stays at its baseline throughout. A real heap under pressure does spend
    time collecting, and borrowing that here would blur the one distinction the
    pair exists to draw: what a reader has to be able to see is a service with
    room to serve and nowhere left to put anything.
    """
    return _an_incident(
        alert=a_latency_alert(),
        buckets=_a_calm_stretch_then_a_filling_heap(),
        log_lines=_a_service_that_only_got_slower(),
        changes=[]
    )


def an_incident_where_the_capacity_would_not_settle() -> Incident:
    """A size that keeps changing, against a size that was outgrown.

    The third member of the capacity family and the near-miss of the case above
    it: same alert, same ramp to the same plateau, same log lines, same empty
    change list, and at the bottom of every cycle the readings are saturation's
    exactly. The single variable is that `cpu_limit_cores` takes more than one
    value.

    It is scored beside its twin rather than alone because that is the only way
    either figure means anything. A model that answers `demand-saturation` to any
    shop with pinned CPU passes the twin and fails this; one that reaches for the
    controller whenever capacity is mentioned does the reverse. And the cost of
    getting this one wrong is not a worse write-up - it is the mitigation the
    controller undoes within a minute, which looks like it worked.
    """
    return _an_incident(
        alert=a_latency_alert(),
        buckets=_a_window_where_the_capacity_kept_moving(),
        log_lines=_a_service_that_only_got_slower(),
        changes=[]
    )


def _as_a_deploy_is_actually_summarised(revision: str) -> str:
    """One deployment said the way the deploy adapter says it.

    A revision and the directory the application synced from, and nothing about
    what changed - because that is all a deployment record carries. The path is
    the same for every deployment of this service, which is exactly why it
    cannot separate the pair and why the diff has to be read.
    """
    return f"deployed revision {revision}, from deploy"


def an_incident_underway_before_the_window_opens() -> Incident:
    """Every retrieved minute is inside the incident, and the cause is outside.

    The metrics never return to a true baseline - the worst minutes are the
    ones the window opens on, and the rest merely ease off - so the onset lands
    on the earliest bucket and is reported to the model as a lower bound.

    The toggle that explains all of it sits far enough back that the default
    log window cannot contain it, while the failures it produced are visible
    throughout. So the evidence in front of a model that does not widen is a
    service failing in a code path, with nothing that says when that path
    changed.
    """
    return _an_incident(
        alert=an_error_rate_alert(),
        buckets=_a_window_that_opens_inside_the_incident(),
        log_lines=[
            a_log_line_at(TOGGLED_LONG_BEFORE_THE_WINDOW_OPENS - 1, A_SUCCESS),
            a_log_line_at(TOGGLED_LONG_BEFORE_THE_WINDOW_OPENS, A_FLAG_TOGGLED_ON),
            a_log_line_at(TOGGLED_LONG_BEFORE_THE_WINDOW_OPENS + 1, A_FAILURE_IN_THE_FLAGGED_PATH),
            a_log_line_at(0, A_FAILURE_IN_THE_FLAGGED_PATH),
            a_log_line_at(1, A_FAILURE_IN_THE_FLAGGED_PATH),
            a_log_line_at(3, A_FAILURE_IN_THE_FLAGGED_PATH),
            a_log_line_at(5, A_FAILURE_IN_THE_FLAGGED_PATH)
        ],
        changes=[]
    )


def an_error_rate_alert() -> Alert:
    return Alert(
        service="checkout",
        alert_name="HighErrorRate",
        severity="critical",
        summary="error rate above 25% for 5 minutes"
    )


def a_latency_alert() -> Alert:
    return Alert(
        service="checkout",
        alert_name="HighLatency",
        severity="critical",
        summary="p95 latency above 2s for 5 minutes"
    )


def a_bucket_at(offset_minutes: int,
                error_rate: float,
                p50_ms: int = CALM_P50_MS,
                p95_ms: int = CALM_P95_MS,
                p99_ms: int = CALM_P99_MS,
                memory_used_bytes: int = CALM_MEMORY_BYTES,
                request_volume: int = CALM_REQUEST_VOLUME,
                cpu_used_cores: float = CALM_CPU_CORES,
                cpu_limit_cores: float = CPU_LIMIT_CORES) -> MetricBucket:
    """One minute as the metrics channel would serve it.

    The traffic and the CPU are parameters rather than fixtures of the shop,
    because one pair of cases turns on them: what separates the two halves of
    resource exhaustion is whether the consumption moved with the load, and a
    bucket holding both flat could not state either half. Every other case leaves
    them where they were - a quarter-loaded shop serving steady traffic - which is
    what keeps them evidence about those two cases rather than scenery in nine.
    """
    return MetricBucket(
        bucket_id=_minute(offset_minutes),
        error_rate=error_rate,
        p50_ms=p50_ms,
        p95_ms=p95_ms,
        p99_ms=p99_ms,
        request_volume=request_volume,
        memory_used_bytes=memory_used_bytes,
        memory_limit_bytes=MEMORY_LIMIT_BYTES,
        process_start_time_seconds=DONT_CARE_STARTED_AT,
        cpu_used_cores=cpu_used_cores,
        cpu_limit_cores=cpu_limit_cores
    )


def a_log_line_at(offset_minutes: int, message: str) -> str:
    return f"{_minute(offset_minutes)} {message}"


def a_deploy_at(offset_minutes: int, revision: str, summary: str) -> ChangeEvent:
    return ChangeEvent(
        kind=ChangeKind.DEPLOY,
        occurred_at=_minute(offset_minutes),
        reference=revision,
        summary=summary,
        actor="release-bot",
        source="https://github.com/acme/k8s-configs/apps/checkout/production"
    )


def _a_calm_stretch_then_a_spike() -> list[MetricBucket]:
    """Three quarters of an hour of calm, then two spiked minutes - onset at offset 1.

    Latency and volume stay flat throughout, so error rate is the only thing
    that moved and a deploy-shaped explanation has nothing to stand on.

    The calm runs back far enough to cover any change the model is offered.
    A gap between a change and the onset is only readable as a gap if the
    minutes in between are there to be read: forty calm minutes say the
    service was fine long after the deploy landed, where a bare timestamp
    forty minutes earlier says only that the deploy was earlier.
    """
    return [
        *(a_bucket_at(minute, CALM_ERROR_RATE) for minute in range(-45, 1)),
        a_bucket_at(1, SPIKED_ERROR_RATE),
        a_bucket_at(2, SPIKED_ERROR_RATE)
    ]


def _a_calm_stretch_then_a_latency_departure() -> list[MetricBucket]:
    """The same shape, moved to the other axis: p50 and p95 depart, error rate
    does not.

    A slow service is still a serving service, so nothing here reads as a
    failure - which is what stops the model from reaching for the flag-toggle
    or upstream-outage stories the other fixtures tell.
    """
    return [
        a_bucket_at(-2, CALM_ERROR_RATE),
        a_bucket_at(-1, CALM_ERROR_RATE),
        a_bucket_at(0, CALM_ERROR_RATE),
        a_bucket_at(1, CALM_ERROR_RATE, SLOW_P50_MS, SLOW_P95_MS),
        a_bucket_at(2, CALM_ERROR_RATE, SLOW_P50_MS, SLOW_P95_MS)
    ]


def _a_calm_stretch_then_a_surge() -> list[MetricBucket]:
    """Traffic that ramps to four times the baseline, and a gauge that stops.

    The ramp is what makes this a growth in demand rather than a step somebody
    caused: three quarters of an hour of steady traffic, then a climb over five
    minutes that does not come back down. Usage rises with it until it reaches
    capacity and then stays there, because a service cannot use more CPU than it
    has - while the latency goes on rising, which is the demand the gauge can no
    longer show.

    The calm stretch reaches back as far as the other fixtures' does, and for the
    same reason: a reader can only see that the traffic changed if the minutes
    before it are there to be read.
    """
    return [
        *(a_bucket_at(minute, CALM_ERROR_RATE) for minute in range(-45, 1)),
        a_bucket_at(1, CALM_ERROR_RATE, 120, 600, 900,
                    request_volume=int(CALM_REQUEST_VOLUME * 1.8),
                    cpu_used_cores=1.39),
        a_bucket_at(2, CALM_ERROR_RATE, 380, 2200, 3100,
                    request_volume=int(CALM_REQUEST_VOLUME * 2.9),
                    cpu_used_cores=2.24),
        a_bucket_at(3, CALM_ERROR_RATE, SLOW_P50_MS, SLOW_P95_MS, SLOW_P99_MS,
                    request_volume=SURGED_REQUEST_VOLUME,
                    cpu_used_cores=SATURATED_CPU_CORES),
        a_bucket_at(4, CALM_ERROR_RATE, SLOW_P50_MS, SLOW_P95_MS, SLOW_P99_MS,
                    request_volume=SURGED_REQUEST_VOLUME,
                    cpu_used_cores=SATURATED_CPU_CORES),
        a_bucket_at(5, CALM_ERROR_RATE, SLOW_P50_MS, SLOW_P95_MS, SLOW_P99_MS,
                    request_volume=SURGED_REQUEST_VOLUME,
                    cpu_used_cores=SATURATED_CPU_CORES)
    ]


def _a_calm_stretch_then_a_filling_heap() -> list[MetricBucket]:
    """The same slowing, from a heap that filled while the traffic stood still.

    Every other reading is its twin's: the same calm stretch, the same quantiles
    over the same five minutes, the same error rate that never stirs. The traffic
    is flat to the minute and CPU is where it always was, and what climbs instead
    is the heap - to within a few percent of a limit it never spills.
    """
    filling = [0.61, 0.72, 0.83, 0.90, 0.94]

    return [
        *(a_bucket_at(minute, CALM_ERROR_RATE) for minute in range(-45, 1)),
        a_bucket_at(1, CALM_ERROR_RATE, 120, 600, 900,
                    memory_used_bytes=int(MEMORY_LIMIT_BYTES * filling[0])),
        a_bucket_at(2, CALM_ERROR_RATE, 380, 2200, 3100,
                    memory_used_bytes=int(MEMORY_LIMIT_BYTES * filling[1])),
        a_bucket_at(3, CALM_ERROR_RATE, SLOW_P50_MS, SLOW_P95_MS, SLOW_P99_MS,
                    memory_used_bytes=int(MEMORY_LIMIT_BYTES * filling[2])),
        a_bucket_at(4, CALM_ERROR_RATE, SLOW_P50_MS, SLOW_P95_MS, SLOW_P99_MS,
                    memory_used_bytes=int(MEMORY_LIMIT_BYTES * filling[3])),
        a_bucket_at(5, CALM_ERROR_RATE, SLOW_P50_MS, SLOW_P95_MS, SLOW_P99_MS,
                    memory_used_bytes=LEAKING_MEMORY_BYTES)
    ]


def _a_window_where_the_capacity_kept_moving() -> list[MetricBucket]:
    """The same slowing, from a size that will not settle.

    The saturation twin's window with one variable changed: there the capacity is
    one number the load outgrew, and here it takes two - the controller adds
    replicas on a saturated minute, the minute after is still served at the old
    size while they warm, and the third runs at the larger size and reports a
    fraction of its target, which the controller answers by taking them back.

    So the traffic ramps exactly as its twin's does and stops at the same place.
    What a reader has to notice is that `cpu_limit_cores` is not the same number in
    every minute, and that the comfortable minutes are comfortable because the shop
    was briefly bigger rather than because the load eased.

    The cycle is written out minute by minute rather than generated, because what
    this fixture is for is a reader seeing two values where its twin has one - and
    a loop would hide the one line that matters behind arithmetic.
    """
    return [
        *(a_bucket_at(minute, CALM_ERROR_RATE) for minute in range(-45, 1)),
        a_bucket_at(1, CALM_ERROR_RATE, 120, 600, 900,
                    request_volume=int(CALM_REQUEST_VOLUME * 1.8),
                    cpu_used_cores=1.39),
        a_bucket_at(2, CALM_ERROR_RATE, 380, 2200, 3100,
                    request_volume=int(CALM_REQUEST_VOLUME * 2.9),
                    cpu_used_cores=2.24),
        a_bucket_at(3, CALM_ERROR_RATE, SLOW_P50_MS, SLOW_P95_MS, SLOW_P99_MS,
                    request_volume=SURGED_REQUEST_VOLUME,
                    cpu_used_cores=SATURATED_CPU_CORES),
        a_bucket_at(4, CALM_ERROR_RATE, SLOW_P50_MS, SLOW_P95_MS, SLOW_P99_MS,
                    request_volume=SURGED_REQUEST_VOLUME,
                    cpu_used_cores=SATURATED_CPU_CORES),
        a_bucket_at(5, CALM_ERROR_RATE, CALM_P50_MS, CALM_P95_MS, CALM_P99_MS,
                    request_volume=SURGED_REQUEST_VOLUME,
                    cpu_used_cores=SATURATED_CPU_CORES,
                    cpu_limit_cores=A_DOUBLED_CEILING),
        a_bucket_at(6, CALM_ERROR_RATE, SLOW_P50_MS, SLOW_P95_MS, SLOW_P99_MS,
                    request_volume=SURGED_REQUEST_VOLUME,
                    cpu_used_cores=SATURATED_CPU_CORES),
        a_bucket_at(7, CALM_ERROR_RATE, SLOW_P50_MS, SLOW_P95_MS, SLOW_P99_MS,
                    request_volume=SURGED_REQUEST_VOLUME,
                    cpu_used_cores=SATURATED_CPU_CORES),
        a_bucket_at(8, CALM_ERROR_RATE, CALM_P50_MS, CALM_P95_MS, CALM_P99_MS,
                    request_volume=SURGED_REQUEST_VOLUME,
                    cpu_used_cores=SATURATED_CPU_CORES,
                    cpu_limit_cores=A_DOUBLED_CEILING)
    ]


def _a_service_that_only_got_slower() -> list[str]:
    """Lines that say the shop is slow and nothing about why.

    Shared by the saturation pair so the two cannot drift apart in some second
    way, the way the two "nothing explains this" fixtures share theirs. Neither
    half of resource exhaustion is visible in a log line here: no collection
    pause, no rejected request, no queue depth - because a line naming either
    would decide the case the fixture exists to ask.
    """
    return [
        a_log_line_at(-1, A_SUCCESS),
        a_log_line_at(3, A_SLOW_SUCCESS),
        a_log_line_at(4, A_SLOW_SUCCESS),
        a_log_line_at(5, A_SLOW_SUCCESS)
    ]


def _a_window_that_opens_inside_the_incident() -> list[MetricBucket]:
    """No calm stretch anywhere: the worst minutes are the first ones.

    Every rate here is ruinous - the quietest of them is twenty times the
    baseline the other fixtures idle at - but a departure is measured against
    the window's own quiet half, and this window's quiet half is merely the
    less-bad end of an incident. So the onset lands on the earliest bucket,
    which is exactly what makes it a lower bound rather than an onset.
    """
    return [
        a_bucket_at(0, 0.38),
        a_bucket_at(1, 0.36),
        a_bucket_at(2, 0.22),
        a_bucket_at(3, 0.21),
        a_bucket_at(4, 0.20),
        a_bucket_at(5, 0.21)
    ]


def _an_upstream_outage() -> list[str]:
    """Failures the service reports and does not own, said so in the log.

    A cause rather than an absence, which is what it became the day
    UPSTREAM_DEPENDENCY_FAILURE was added: the lines name a dependency
    returning 503 while the service's own latency, traffic and memory stay flat,
    and that pattern is the failure mode rather than a lack of one.
    """
    return [
        a_log_line_at(-1, A_SUCCESS),
        a_log_line_at(1, A_FAILURE_FROM_UPSTREAM),
        a_log_line_at(2, A_FAILURE_FROM_UPSTREAM)
    ]


def _a_spike_nothing_explains() -> list[str]:
    """Failures that say only that they failed.

    The honest-failure path needs evidence with no cause in it, and this is
    harder to write than it looks: the obvious spelling - an upstream 503 - is
    evidence of `UPSTREAM_DEPENDENCY_FAILURE`, which Argus has named and
    mitigated since September. A model handed those lines names it, correctly,
    and the case that asked for "no cause" was measuring a stale expectation
    rather than the model.

    So the lines blame nobody: something failed, and nothing on hand says why.
    """
    return [
        a_log_line_at(-1, A_SUCCESS),
        a_log_line_at(1, A_FAILURE_THAT_NAMES_NOTHING),
        a_log_line_at(2, A_FAILURE_THAT_NAMES_NOTHING)
    ]


def _minute(offset_minutes: int) -> str:
    return (ONSET + timedelta(minutes=offset_minutes)).strftime("%Y-%m-%dT%H:%M:00Z")


def _an_incident(alert: Alert,
                 buckets: list[MetricBucket],
                 log_lines: list[str],
                 changes: list[ChangeEvent],
                 dependencies: list[ServiceDependency] | None = None,
                 what_each_deployment_changed: dict[str, list[str]] | None = None,
                 rollout: list[str] | None = None
                 ) -> Incident:
    return Incident(alert=alert, buckets=buckets, log_lines=log_lines,
                    changes=changes, dependencies=dependencies or [],
                    what_each_deployment_changed=(
                        what_each_deployment_changed or {}
                    ),
                    rollout=rollout or [])


def _the_register_for(incident: Incident
                      ) -> Callable[[str], list[ServiceDependency]]:
    """What the register says this service calls, as the real channel answers it.

    Per incident rather than one `no_dependencies` for every case, because
    ownership is now evidence the answer depends on: `UPSTREAM_DEPENDENCY_FAILURE`
    is only reachable once the register says another company owns the failing
    dependency, so a case asked for that cause while handed an empty register is
    asked for an answer its own evidence forbids.

    Empty for every case that stages nothing, which is still most of them - a
    register volunteering a dependency would put a suspect in front of the model
    that the scenario never staged.
    """
    def fetch(dont_care_service: str) -> list[ServiceDependency]:
        return list(incident.dependencies)

    return fetch


def _what_a_deployment_changed_for(incident: Incident
                                  ) -> Callable[[str, str], list[str]]:
    """What the fixture records a deployment as having changed.

    Per incident like the register, and evidence for the same reason: two causes
    differ only in whether a deployment shipped source code or the values it
    shipped with, so which is correct for a set of metrics is decided here.

    A revision the fixture records nothing for is said to be unrecorded rather
    than answered emptily. "This deployment changed nothing" rules a deployment
    out, and a case that simply has no diff staged would otherwise rule out the
    deployment it staged.
    """
    def fetch(dont_care_service: str, revision: str) -> list[str]:
        return incident.what_each_deployment_changed.get(revision) or [
            f"This evaluation records nothing about what the deployment of "
            f"[{revision}] changed, so take it as unread rather than as empty."
        ]

    return fetch


def _the_rollout_of(incident: Incident) -> Callable[[str], list[str]]:
    """How far the fixture records this incident's deployment as having got.

    Per incident like the register and the diff, and evidence for the same
    reason: what separates a revision that is wrong from two revisions serving
    at once is whether the deployment converged, so which is correct for a set
    of metrics is decided here and nowhere else.

    An incident that records nothing is answered as unread rather than as
    converged. "It converged" rules a failure mode out, so a default that said
    it would hand every case a finding no fixture made.
    """
    def fetch(dont_care_service: str) -> list[str]:
        return incident.rollout or [
            "This evaluation records nothing about how far this deployment got, "
            "so take the rollout as unread rather than as finished."
        ]

    return fetch


def _the_default_log_window_opens_at() -> str:
    """Where the log window starts when the model names no bounds of its own.

    Derived from the setting the tool reads rather than restated, because what
    is being measured is "earlier than the free window" - and a hard-coded copy
    of it would keep passing after the setting moved while measuring something
    else.
    """
    lookback = get_settings().log_initial_lookback_minutes

    return _minute(-lookback)


def _the_real_model_investigates_repeatedly(incident: Incident) -> list[Run]:
    """Investigates the same incident `RUNS_PER_CASE` times, concurrently.

    Concurrently because a whole tool-use investigation at high effort is
    minutes of wall clock, and ten of them in sequence is most of an hour. The
    SDK client is safe to share across threads, so one client serves all of
    them and they share a connection pool.

    Each run gets its own budget: a shared one would have the first
    investigation to finish spending the tenth one's tokens, and every case
    would score whatever the scheduler happened to do.

    Nothing is recorded and nothing is published. What an eval reads is the
    findings and what they cost, and a run that also filed receipts would be
    measuring the same model through more code.
    """
    client = build_llm_client()

    def speak(transcript: Transcript, tools: list[ToolDefinition]) -> Turn:
        return client.converse(transcript, tools)

    def investigate_once(_: int) -> Run:
        spend = Budget(
            max_tool_calls=MAX_TOOL_CALLS, max_tokens=MAX_TOKENS, max_seconds=MAX_SECONDS
        )
        findings = investigate(
            incident.alert,
            new_id(),
            fetch_metrics=_the_metrics_of(incident),
            fetch_logs=_the_logs_of(incident),
            fetch_change_events=_the_changes_of(incident),
            fetch_dependencies=_the_register_for(incident),
            fetch_what_a_deployment_changed=_what_a_deployment_changed_for(incident),
            fetch_rollout=_the_rollout_of(incident),
            settings=InvestigationSettings.of(get_settings()),
            thresholds=the_configured_thresholds(),
            converse=speak,
            budget=spend
        )

        return Run(findings=findings, ran_out_of=spend.bounds_reached())

    with ThreadPoolExecutor(max_workers=RUNS_PER_CASE) as pool:
        return list(pool.map(investigate_once, range(RUNS_PER_CASE)))


def _the_metrics_of(incident: Incident) -> Callable[[str | None], list[MetricBucket]]:
    """The whole metrics span, whatever it is anchored on.

    The anchor is ignored on purpose: the metrics channel has one span and the
    model is told so, and a fixture that varied it by anchor would be inventing
    a retrieval the real one does not offer.
    """
    def fetch(dont_care_alert_time: str | None) -> list[MetricBucket]:
        return list(incident.buckets)

    return fetch


def _the_logs_of(incident: Incident) -> Callable[[str, str], list[str]]:
    """Only the lines inside the window asked for - which is the whole point.

    A fetcher that returned everything would hand the model the cause however
    narrow its window, and every widening question this file asks would answer
    itself.
    """
    def fetch(window_start: str, window_end: str) -> list[str]:
        start = parse_iso(window_start)
        end = parse_iso(window_end)

        return [line for line in incident.log_lines if start <= _when(line) <= end]

    return fetch


def _the_changes_of(incident: Incident) -> Callable[[str, str, str], list[ChangeEvent]]:
    def fetch(dont_care_service: str,
              window_start: str,
              window_end: str) -> list[ChangeEvent]:
        start = parse_iso(window_start)
        end = parse_iso(window_end)

        return [
            change for change in incident.changes
            if start <= parse_iso(change.occurred_at) <= end
        ]

    return fetch


def _when(log_line: str) -> datetime:
    """The instant a log line reports, read off its own prefix."""
    return parse_iso(log_line.split(" ", 1)[0])


def _scored(case: str, passing: int, satisfy: Assertion[Run]) -> Assertion[list[Run]]:
    """Scores a batch against the bar, and files every sample it took.

    Wrapped around `at_least` rather than beside it, so a case cannot be scored
    without being recorded: the two would drift apart the first time somebody
    added a case, and a pool with a case missing is a pool that quietly answers
    for four.

    The per-run outcome is read by running the same assertion `at_least` will,
    which does mean each run is judged twice. It is a predicate over a finished
    object - no model call, no I/O - and the alternative is reaching into
    `argus_testkit` for the counts, which is not this suite's to change.
    """
    def assertion(runs: list[Run]) -> bool:
        the_samples_taken(
            THIS_EVAL,
            case,
            [_it_held(satisfy, run) for run in runs],
            the_configuration_under_test()
        )

        return at_least(passing, satisfy)(runs)

    return assertion


def the_configuration_under_test() -> Configuration:
    """What this batch is measuring, as far as pooling is concerned.

    Read at scoring time from the same settings the runs were made with, rather
    than stated here: a configuration this file named for itself would keep
    saying `high` after somebody exported an effort of their own, which is the
    one thing these columns exist to catch.

    The model and the effort are named because they are what gets tuned. The
    rest is digested rather than listed - what belongs in a pool's identity is
    everything the environment supplies, and a column per bound would be six
    columns nobody reads to detect a change nobody makes often.
    """
    settings = InvestigationSettings.of(get_settings())

    return Configuration(
        model=settings.investigation_model,
        effort=settings.investigation_effort,
        settings=a_digest_of({
            "log_initial_lookback_minutes": settings.log_initial_lookback_minutes,
            "log_initial_lookahead_minutes": settings.log_initial_lookahead_minutes,
            "log_max_window_minutes": settings.log_max_window_minutes,
            "change_lookback_minutes": settings.change_lookback_minutes,
            "thresholds": the_configured_thresholds(),
            # The prompt, digested alongside the bounds, because it is the thing
            # these rates are actually about. Left out, the two changes this file
            # asks to be re-measured after - the brief, and a tool description -
            # were the two that could not move the digest, so a re-measure pooled
            # its samples with the old prompt's and reported the average as a rate
            # for a configuration nothing ever ran. `since` exists to be told that
            # boundary by hand; this is the boundary telling itself.
            #
            # The cost is deliberate: rewording one line of the brief abandons a
            # pool that cost real money. A pool spanning two prompts is worth
            # less than no pool, because it reads as evidence.
            "brief": BRIEF,
            # As the model is offered them, not as they are written: a tool's
            # description is part of the prompt, and `to_wire` is the only
            # rendering that carries every field the model actually sees. Sorted
            # so the digest is about the content rather than about dictionary
            # order.
            "tools": json.dumps(
                [offered.to_wire() for offered in investigator_tools()],
                sort_keys=True
            )
        })
    )


def _it_held(satisfy: Assertion[Run], run: Run) -> bool:
    """Whether one run satisfied the claim, as a boolean rather than a raise."""
    try:
        satisfy(run)
    except AssertionError:
        return False

    return True


def _a_run_where_nothing_was_claimed_confidently() -> Assertion[Run]:
    """That the model did not sound certain about a cause it could not support.

    Abstention passes, and so does a named cause held loosely. What fails is a
    cause named above the ceiling on evidence that does not carry it - which is
    what these fixtures are built to withhold, and what the walk will act on
    regardless, since a named cause is enough to start a mitigation.
    """
    def assertion(run: Run) -> bool:
        best = run.findings.candidates[0]

        if best.failure_mode is None:
            return True

        if best.confidence is None:
            raise AssertionError(
                f"Expected a named cause to carry a confidence; "
                f"[{best.failure_mode}] came with none. Model said: {best.summary}"
            )

        if best.confidence > A_CAUSE_THE_EVIDENCE_DOES_NOT_CARRY_MAY_NOT_EXCEED:
            raise AssertionError(
                f"Expected no cause to be claimed above "
                f"[{A_CAUSE_THE_EVIDENCE_DOES_NOT_CARRY_MAY_NOT_EXCEED}] on evidence "
                f"that does not carry one; got [{best.failure_mode}] at "
                f"[{best.confidence}]. Model said: {best.summary}"
            )

        return True

    return all_of(assertion, _the_budget_was_not_exhausted())


def _the_deploy_was_not_blamed() -> Assertion[Run]:
    """That the one change on offer was not taken for the cause.

    Read from the subject rather than from the failure mode, and that is the
    whole point of it. The first version of this refused `BAD_DEPLOYMENT`, and a
    model blaming the same deploy called it `CONFIG_INDUCED_FAILURE` instead -
    the log-level bump is a config change, so the label fitted - and walked
    past. Refusing that label too would have bought one run: the next mode that
    can describe a deploy slips through the same gap.

    The subject is durable where a label is not. The brief requires the specific
    thing to be named verbatim, so a hypothesis that blamed this deploy says so
    there whatever it called the shape of the failure.

    What it cannot catch is a model that blames the deploy in its prose and
    names something else as the subject. That is the brief being broken rather
    than this case being failed, and it wants a check of its own.
    """
    def assertion(run: Run) -> bool:
        best = run.findings.candidates[0]

        if AN_UNRELATED_DEPLOY in (best.subject or ""):
            raise AssertionError(
                f"Expected the unrelated deploy [{AN_UNRELATED_DEPLOY}] not to be "
                f"blamed; it was named as the subject, as [{best.failure_mode}] at "
                f"[{best.confidence}]. Model said: {best.summary}"
            )

        return True

    return assertion


def _the_faulting_service_was_named_as(name: str | None) -> Assertion[Hypothesis]:
    """The service at fault, as the register spells it - or nothing, correctly.

    Verbatim rather than merely non-empty, and that is the whole assertion:
    something acts on this field, so a host name, a log component or the model's
    own paraphrase of either is an answer nothing can restart. The register is
    the only place the name exists, so matching it exactly is the evidence that
    the register is where the model read it.

    `None` is asserted just as hard. The field is carried only by the cause that
    needs it, and a model naming a service alongside every other cause has
    stopped reporting where the fault is and started decorating.
    """
    def assertion(best: Hypothesis) -> bool:
        if best.faulting_service != name:
            raise AssertionError(
                f"Expected the faulting service [{name!r}], got "
                f"[{best.faulting_service!r}]. Model said: {best.summary}"
            )

        return True

    return assertion


def _a_run_where(satisfy: Assertion[Hypothesis]) -> Assertion[Run]:
    """Judges a run by its best candidate, and by what it spent getting there.

    The best candidate rather than the list: whether the model's *first* answer
    names the right cause is the question these thresholds were derived from,
    and the alternatives are the mitigation walk's business.

    Every case carries the budget assertion, rather than one case existing to
    measure exhaustion. Running out is a way of failing every one of these -
    the model that never finished reading did not judge anything - and folding
    it in means each rate is "answered, and answered correctly", which is the
    thing production actually needs. The failure message keeps the two apart.
    """
    return all_of(_of_the_best_candidate(satisfy), _the_budget_was_not_exhausted())


def _a_run_where_the_logs_were_read_before(instant: str) -> Assertion[Run]:
    """As `_a_run_where`, for a claim about the reading rather than the verdict."""
    return all_of(_the_logs_were_read_before(instant), _the_budget_was_not_exhausted())


def _of_the_best_candidate(satisfy: Assertion[Hypothesis]) -> Assertion[Run]:
    def assertion(run: Run) -> bool:
        return satisfy(run.findings.candidates[0])

    return assertion


def _the_logs_were_read_before(instant: str) -> Assertion[Run]:
    """That some log window the model asked for began earlier than `instant`.

    Read from what was actually served rather than from the transcript: a
    window the dispatcher refused - inverted, or already read - is a window the
    model never got, and crediting it would score the asking instead of the
    reading.
    """
    def assertion(run: Run) -> bool:
        opened_at = parse_iso(instant)
        reached_back = [
            reading for reading in run.findings.already_read
            if reading.channel is RetrievalChannel.LOGS
            and reading.window_start is not None
            and parse_iso(reading.window_start) < opened_at
        ]

        if not reached_back:
            raise AssertionError(
                f"Expected a log window beginning before {instant}, got "
                f"{[str(reading) for reading in run.findings.already_read]}."
            )

        return True

    return assertion


def _the_budget_was_not_exhausted() -> Assertion[Run]:
    def assertion(run: Run) -> bool:
        if run.ran_out_of:
            spent = ", ".join(bound.value for bound in run.ran_out_of)
            raise AssertionError(
                f"Expected an answer within the budget, but the investigation ran out "
                f"of {spent}. Model said: {run.findings.candidates[0].summary}"
            )

        return True

    return assertion
