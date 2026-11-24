"""A write tool's refusal, as a value: what each kind may say, and how it is read.

The kind decides what a caller does next, so a refusal that said what its kind
cannot - a platform on a refusal that is not about one, a change performed on
one nobody overtook, something left behind by one raised before anything was
touched - is refused where it is built rather than acted on wrongly far away.
"""

from __future__ import annotations

import pytest
from argus_testkit.assertions import Assertion, all_of, an_error_was_raised, the_answer_was
from argus_testkit.scenario import Scenario, attempting
from core.models import DeploymentRollbackUndo
from mcp_transport import ToolRefusal, ToolRefusalKind, ToolRefused
from pydantic import ValidationError

SOME_WORDS = "the platform said no"
SOME_PLATFORM = "some-deployment-platform"
SOME_SUSPENSION = DeploymentRollbackUndo(
    application="some-application",
    was_on_history_id=41,
    was_on_revision="0f1e2d3",
    was_syncing_itself=True
)
# Every kind but the one a platform is named on, the one a change is performed
# on, and the two raised before anything was touched.
NOT_ABOUT_A_PLATFORM = [kind for kind in ToolRefusalKind
                        if kind is not ToolRefusalKind.PLATFORM_UNREACHABLE]
NOBODY_OVERTOOK = [kind for kind in ToolRefusalKind
                   if kind is not ToolRefusalKind.CHANGED_SINCE]
RAISED_BEFORE_ANYTHING_WAS_TOUCHED = [ToolRefusalKind.RUN_LOST, ToolRefusalKind.EXHAUSTED]


@pytest.mark.unit
@pytest.mark.parametrize("kind", NOT_ABOUT_A_PLATFORM)
def test_a_refusal_not_about_a_platform_names_none(kind: ToolRefusalKind) -> None:
    Scenario() \
        .when(attempting(lambda: ToolRefusal(kind=kind, said=SOME_WORDS, platform=SOME_PLATFORM))) \
        .then(an_error_was_raised(ValidationError))


@pytest.mark.unit
def test_a_platform_that_did_not_answer_is_named() -> None:
    Scenario() \
        .when(attempting(lambda: ToolRefusal(kind=ToolRefusalKind.PLATFORM_UNREACHABLE,
                                             said=SOME_WORDS))) \
        .then(an_error_was_raised(ValidationError))


@pytest.mark.unit
@pytest.mark.parametrize("kind", NOBODY_OVERTOOK)
def test_only_a_change_somebody_overtook_says_it_was_performed(kind: ToolRefusalKind) -> None:
    Scenario() \
        .when(attempting(lambda: ToolRefusal(
            kind=kind, said=SOME_WORDS, performed=True,
            platform=SOME_PLATFORM if kind is ToolRefusalKind.PLATFORM_UNREACHABLE else None
        ))) \
        .then(an_error_was_raised(ValidationError))


@pytest.mark.unit
@pytest.mark.parametrize("kind", RAISED_BEFORE_ANYTHING_WAS_TOUCHED)
def test_a_refusal_raised_before_anything_was_touched_leaves_nothing_behind(
    kind: ToolRefusalKind
) -> None:
    Scenario() \
        .when(attempting(lambda: ToolRefusal(kind=kind, said=SOME_WORDS,
                                             left_behind=SOME_SUSPENSION))) \
        .then(an_error_was_raised(ValidationError))


@pytest.mark.unit
@pytest.mark.parametrize("kind", list(ToolRefusalKind))
def test_only_a_refusal_nobody_accounted_for_does_not_know_what_it_left(
    kind: ToolRefusalKind
) -> None:
    Scenario() \
        .given(refusal := _a_refusal_of(kind)) \
        .when(lambda: refusal.left_behind_known) \
        .then(the_answer_was(kind is not ToolRefusalKind.UNACCOUNTED))


@pytest.mark.unit
def test_a_platform_that_did_not_answer_is_said_before_the_words() -> None:
    # What a person reads names the platform first, as the tier always said it.
    Scenario() \
        .given(refusal := ToolRefusal(kind=ToolRefusalKind.PLATFORM_UNREACHABLE,
                                      said=SOME_WORDS, platform=SOME_PLATFORM)) \
        .when(lambda: refusal.words) \
        .then(the_answer_was(f"{SOME_PLATFORM} {SOME_WORDS}"))


@pytest.mark.unit
def test_the_words_are_said_without_the_space_around_them() -> None:
    Scenario() \
        .given(refusal := ToolRefusal(kind=ToolRefusalKind.LEFT_BEHIND_KNOWN,
                                      said=f"  {SOME_WORDS} ")) \
        .when(lambda: refusal.words) \
        .then(the_answer_was(SOME_WORDS))


@pytest.mark.unit
def test_a_refusal_raised_says_its_words_and_carries_the_refusal_whole() -> None:
    # Its message is what a log line and a span say, and what a person reads.
    Scenario() \
        .given(refusal := ToolRefusal(kind=ToolRefusalKind.PLATFORM_UNREACHABLE,
                                      said=SOME_WORDS, platform=SOME_PLATFORM,
                                      left_behind=SOME_SUSPENSION)) \
        .when(lambda: ToolRefused(refusal)) \
        .then(all_of(
            _it_says(f"{SOME_PLATFORM} {SOME_WORDS}"),
            _it_carries(refusal)
        ))


def _a_refusal_of(kind: ToolRefusalKind) -> ToolRefusal:
    """A refusal of `kind` saying only what every kind may say."""
    return ToolRefusal(
        kind=kind, said=SOME_WORDS,
        platform=SOME_PLATFORM if kind is ToolRefusalKind.PLATFORM_UNREACHABLE else None
    )


def _it_says(expected: str) -> Assertion[ToolRefused]:
    def assertion(raised: ToolRefused) -> bool:
        if str(raised) != expected:
            raise AssertionError(f"Expected the refusal to say [{expected}], and it said "
                                 f"[{raised}].")

        return True

    return assertion


def _it_carries(expected: ToolRefusal) -> Assertion[ToolRefused]:
    def assertion(raised: ToolRefused) -> bool:
        if raised.refusal != expected:
            raise AssertionError(f"Expected the refusal to carry {expected!r}, and it carried "
                                 f"{raised.refusal!r}.")

        return True

    return assertion
