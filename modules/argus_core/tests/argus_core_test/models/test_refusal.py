"""Why an action was not taken, in the one sentence every reader says it in.

The timeline, a candidate's row and the review all say why the gate refused,
and three spellings of one reason read as three reasons. Each sentence carries
its own subject, so it reads the same after "Refused to act - ", as a row on
its own, and as a review's reason.
"""

from __future__ import annotations

import pytest
from argus_core.models import Refusal, why_it_was_refused
from argus_testkit import Assertion, Scenario, the_answer_was


@pytest.mark.unit
@pytest.mark.parametrize(("refusal", "said"), [
    (Refusal.NO_MITIGATION_PROPOSED,
     "nothing in the evidence said what to act on to test the candidate"),
    (Refusal.NAMED_CHANGE_NOT_RECORDED,
     "the change the candidate names is not in the record of what changed, so undoing "
     "it is left to a person"),
    (Refusal.SOMEBODY_ELSES_SERVICE,
     "the failure is in a service another company runs, and nothing Argus can do "
     "reaches it"),
    (Refusal.WOULD_UNDO_A_MEANT_CHANGE,
     "the only action that would test the candidate undoes a change that was made "
     "on purpose"),
    (Refusal.NOT_A_GENERIC_MITIGATION,
     "the action that would test the candidate is not of a kind Argus may take "
     "unasked"),
    (Refusal.ALREADY_TRIED_ENOUGH,
     "the action has already been tried on this subject as often as the incident "
     "allows"),
    (Refusal.OUTSIDE_WHAT_ARGUS_MAY_TOUCH,
     "the action that would test the candidate is addressed to a service outside "
     "the estate Argus may act on"),
    (Refusal.NOTHING_COULD_CONFIRM_IT,
     "nothing would say whether the action that would test the candidate worked "
     "inside the time Argus waits, so it is recommended rather than taken")
], ids=["no-mitigation-proposed", "named-change-not-recorded", "somebody-elses-service",
        "would-undo-a-meant-change", "not-a-generic-mitigation", "already-tried-enough",
        "outside-what-argus-may-touch", "nothing-could-confirm-it"])
def test_each_refusal_is_said_in_its_one_sentence(refusal: Refusal, said: str) -> None:
    # Every one the review can show names what it is about - "the candidate",
    # "the action that would test the candidate" - because a review's reason
    # has no line before it to lend a bare "it" or "the action" a meaning. The
    # cap is the exception: the review never shows it, and "would test" is
    # wrong of a candidate that was tested.
    #
    # The two that reach the gate with no action say what was missing rather
    # than that nothing was proposed. Told "no mitigation was proposed for the
    # candidate" of a flag the provider had no record of changing, a write-up
    # said Argus had no mitigation for a flag, asked for one to be built, and
    # never told a person to switch the flag off.
    Scenario() \
        .given(refusal) \
        .when(lambda: why_it_was_refused(refusal)) \
        .then(the_answer_was(said))


@pytest.mark.unit
def test_every_refusal_has_a_sentence() -> None:
    # The lookup is a subscript, not a `get`, so a value with no sentence does
    # not degrade to a blank - it raises, in the gate before anything is tried
    # and in the narration that exists to say what happened.
    #
    # Over the whole enum rather than per member: what must hold is that no
    # refusal reaches a reader as a value nobody wrote a sentence for, and a
    # test naming the seven that exist today says nothing about the eighth.
    Scenario() \
        .given(every_reason_to_refuse := list(Refusal)) \
        .when(lambda: {
            refusal: _what_a_reader_is_told_about(refusal)
            for refusal in every_reason_to_refuse
        }) \
        .then(_every_refusal_was_put_into_words())


def _what_a_reader_is_told_about(refusal: Refusal) -> str:
    """The sentence for one refusal, or the empty string where there is none.

    Caught rather than allowed to raise, so the assertion below names every
    refusal without a sentence instead of the test ending on the first one.
    """
    try:
        return why_it_was_refused(refusal)
    except KeyError:
        return ""


def _every_refusal_was_put_into_words() -> Assertion[dict[Refusal, str]]:
    def assertion(said: dict[Refusal, str]) -> bool:
        wordless = [refusal.value for refusal, sentence in said.items() if not sentence]

        if wordless:
            raise AssertionError(
                f"{sorted(wordless)} have no sentence, so a walk refused for one of "
                f"those reasons fails at the gate, and its narration fails with it."
            )

        return True

    return assertion
