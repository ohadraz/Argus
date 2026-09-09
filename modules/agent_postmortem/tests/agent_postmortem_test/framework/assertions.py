from __future__ import annotations

from decimal import Decimal

from agent_postmortem import PostmortemDocument
from argus_testkit import Assertion

"""What a finished postmortem says, and what it is asked never to say.

Every assertion here reads a document, because a document is the only thing two
suites share: the unit tests each read what their own module returns, and only
`writing` and the component test end up holding a page.

Most of these come in pairs - a figure published and a figure absent - and the
pairing is the point. A postmortem reporting no loss and one that could not
find out leave the same blank, so an assertion that accepted either would pass
on the failure this agent exists to avoid.

Every one of them raises with what it expected and what it got. An assertion
that only returns `False` makes a reader run the test again under a debugger to
learn what a passing document would have looked like.
"""


def reports_root_cause(expected: str) -> Assertion[PostmortemDocument]:
    def assertion(document: PostmortemDocument) -> bool:
        if document.root_cause != expected:
            raise AssertionError(
                f"expected the root cause [{expected}], got [{document.root_cause}]")

        return True

    return assertion


def reports_no_root_cause() -> Assertion[PostmortemDocument]:
    def assertion(document: PostmortemDocument) -> bool:
        if document.root_cause is not None:
            raise AssertionError(
                f"expected no root cause where the model named none, "
                f"got [{document.root_cause}]")

        return True

    return assertion


def reports_executive_summary(expected: str) -> Assertion[PostmortemDocument]:
    def assertion(document: PostmortemDocument) -> bool:
        if document.executive_summary != expected:
            raise AssertionError(
                f"expected the summary [{expected}], got [{document.executive_summary}]")

        return True

    return assertion


def estimates_a_loss_of(expected: Decimal | None) -> Assertion[PostmortemDocument]:
    def assertion(document: PostmortemDocument) -> bool:
        if document.customer_loss_estimate != expected:
            raise AssertionError(
                f"expected an estimate of [{expected}], "
                f"got [{document.customer_loss_estimate}]")

        return True

    return assertion


def estimates_nothing() -> Assertion[PostmortemDocument]:
    def assertion(document: PostmortemDocument) -> bool:
        if document.customer_loss_estimate is not None:
            raise AssertionError(
                f"expected no estimate where a term of it could not be read, "
                f"got [{document.customer_loss_estimate}]")

        return True

    return assertion


def states_the_estimate_is_in(expected: str) -> Assertion[PostmortemDocument]:
    def assertion(document: PostmortemDocument) -> bool:
        if document.estimate_currency != expected:
            raise AssertionError(
                f"expected the estimate to be reported in [{expected}], got "
                f"[{document.estimate_currency}]")

        return True

    return assertion


def reports_engineer_minutes(expected: int) -> Assertion[PostmortemDocument]:
    def assertion(document: PostmortemDocument) -> bool:
        if document.engineer_minutes != expected:
            raise AssertionError(
                f"expected [{expected}] engineer minutes, "
                f"got [{document.engineer_minutes}]")

        return True

    return assertion


def reports_no_engineer_minutes() -> Assertion[PostmortemDocument]:
    def assertion(document: PostmortemDocument) -> bool:
        if document.engineer_minutes is not None:
            raise AssertionError(
                f"expected no engineer minutes where nobody could say, "
                f"got [{document.engineer_minutes}]")

        return True

    return assertion


def reports_engineer_minutes_across(minutes: int,
                                    responders: int) -> Assertion[PostmortemDocument]:
    """The person-minutes, and how many people they were spread across.

    Both in one assertion, because either alone would pass on a document that
    multiplied them: 25 minutes across 2 responders and 50 across 1 differ in
    what they say about the night, and only checking the pair tells them apart.
    """
    def assertion(document: PostmortemDocument) -> bool:
        if document.engineer_minutes != minutes:
            raise AssertionError(
                f"expected [{minutes}] engineer minutes, "
                f"got [{document.engineer_minutes}]")

        if document.responders != responders:
            raise AssertionError(
                f"expected [{minutes}] engineer minutes across [{responders}] "
                f"responder(s), got [{document.responders}] responder(s)")

        return True

    return assertion


def reports_responders(expected: int) -> Assertion[PostmortemDocument]:
    def assertion(document: PostmortemDocument) -> bool:
        if document.responders != expected:
            raise AssertionError(
                f"expected [{expected}] responders, got [{document.responders}]")

        return True

    return assertion


def reports_the_titles(*expected: str) -> Assertion[PostmortemDocument]:
    """Exactly these, and nothing that could identify a person.

    Sorted rather than ordered: who was on it is the fact, and the order two
    people acknowledged in is not something a document should imply.
    """
    def assertion(document: PostmortemDocument) -> bool:
        if sorted(document.responder_titles) != sorted(expected):
            raise AssertionError(
                f"expected the titles {sorted(expected)}, got "
                f"{sorted(document.responder_titles)}")

        return True

    return assertion


def reports_tokens_spent(expected: int) -> Assertion[PostmortemDocument]:
    def assertion(document: PostmortemDocument) -> bool:
        if document.tokens_spent != expected:
            raise AssertionError(
                f"expected [{expected}] tokens spent, got [{document.tokens_spent}]")

        return True

    return assertion


def reports_a_responder_cost_of(expected: Decimal) -> Assertion[PostmortemDocument]:
    def assertion(document: PostmortemDocument) -> bool:
        if document.responder_cost_estimate != expected:
            raise AssertionError(
                f"expected a responder cost of [{expected}], got "
                f"[{document.responder_cost_estimate}]")

        return True

    return assertion


def reports_a_cost_ranging_from(minimum: Decimal,
                                maximum: Decimal) -> Assertion[PostmortemDocument]:
    def assertion(document: PostmortemDocument) -> bool:
        got = (document.responder_cost_minimum, document.responder_cost_maximum)
        if got != (minimum, maximum):
            raise AssertionError(
                f"expected the responder cost to range from [{minimum}] to "
                f"[{maximum}], got {got}")

        return True

    return assertion


def reports_the_cost_in(expected: str) -> Assertion[PostmortemDocument]:
    def assertion(document: PostmortemDocument) -> bool:
        if document.responder_cost_currency != expected:
            raise AssertionError(
                f"expected the responder cost in [{expected}], got "
                f"[{document.responder_cost_currency}]")

        return True

    return assertion


def reports_no_responder_cost() -> Assertion[PostmortemDocument]:
    def assertion(document: PostmortemDocument) -> bool:
        if document.responder_cost_estimate is not None:
            raise AssertionError(
                f"expected no responder cost where the response could not be "
                f"priced, got [{document.responder_cost_estimate}]")

        return True

    return assertion


def discloses_the_assumption(expected: str) -> Assertion[PostmortemDocument]:
    """That exact sentence, for the disclosures published as named constants."""
    def assertion(document: PostmortemDocument) -> bool:
        if expected not in document.assumptions:
            raise AssertionError(
                f"expected the assumption [{expected}], got {document.assumptions}")

        return True

    return assertion


def discloses_an_assumption_naming(subject: str) -> Assertion[PostmortemDocument]:
    """Some assumption mentioning it, for the disclosures written around a value.

    The wording is the document's own, so this asserts the part a reader has to
    be able to find rather than the sentence around it - a test spelling out the
    whole line would fail on a comma.
    """
    def assertion(document: PostmortemDocument) -> bool:
        if not any(subject in assumption for assumption in document.assumptions):
            raise AssertionError(
                f"expected an assumption mentioning [{subject}], "
                f"got {document.assumptions}")

        return True

    return assertion


def discloses_an_assumption_mentioning(label: str,
                                       detail: str) -> Assertion[PostmortemDocument]:
    """One assumption carrying both the label and what it is about.

    Both in the same line rather than both somewhere in the list: a document
    that labelled one assumption and detailed another has disclosed neither.
    """
    def assertion(document: PostmortemDocument) -> bool:
        if not any(label in stated and detail in stated
                   for stated in document.assumptions):
            raise AssertionError(
                f"expected an assumption mentioning [{label}] and [{detail}], "
                f"got {document.assumptions}")

        return True

    return assertion


def discloses_no_assumption_about(unexpected: str) -> Assertion[PostmortemDocument]:
    def assertion(document: PostmortemDocument) -> bool:
        if any(unexpected in stated for stated in document.assumptions):
            raise AssertionError(
                f"expected no apology for a question that was answered, "
                f"got [{unexpected}]")

        return True

    return assertion


def is_marked_complete() -> Assertion[PostmortemDocument]:
    def assertion(document: PostmortemDocument) -> bool:
        if not document.checklist_complete:
            raise AssertionError(
                "expected a document with every field filled to be marked complete")

        return True

    return assertion


def is_marked_incomplete() -> Assertion[PostmortemDocument]:
    def assertion(document: PostmortemDocument) -> bool:
        if document.checklist_complete:
            raise AssertionError(
                "expected a document still missing a field to say so on its face")

        return True

    return assertion
