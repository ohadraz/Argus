"""What a service calls, and the one fact about it only a register holds.

Everything else a dependency has - its name, its host, what it is for - is
discoverable from the caller's own source and its own logs. Whether the thing on
the other end belongs to the same organisation is not, and it is the fact that
decides the response: a neighbour's process can be restarted, and another
company's outage can only be escalated.

So the vocabulary is named rather than inferred from a host name that looks
internal because somebody spelled it that way - and it is deliberately *not*
closed. The register belongs to the organisation and will grow words Argus has
never heard; what must hold is that an unheard-of word is never read as
permission, and that whoever reads the incident afterwards can see which word it
was.
"""

from __future__ import annotations

import pytest
from argus_core.models import Ownership, ServiceDependency
from argus_testkit import Assertion, Scenario, all_of


def a_dependency(ownership: str) -> ServiceDependency:
    return ServiceDependency(
        name="some-service",
        purpose="something the caller needs while it serves a request",
        host="some-service.example",
        owner="some-team",
        ownership=ownership
    )


@pytest.mark.unit
def test_a_dependency_the_organisation_owns_is_one_argus_may_act_on() -> None:
    Scenario() \
        .given(ours := a_dependency(Ownership.INTERNAL)) \
        .when(lambda: ours) \
        .then(all_of(
            _it_is_ours(True),
            _it_is_a_word_argus_knows(True)
        ))


@pytest.mark.unit
def test_a_third_partys_service_is_not_one_argus_may_act_on() -> None:
    # The whole distinction between the two propagation incidents. Read wrong,
    # Argus either escalates something it could have fixed or sends a restart to
    # a company that does not take its calls.
    Scenario() \
        .given(theirs := a_dependency(Ownership.THIRD_PARTY)) \
        .when(lambda: theirs) \
        .then(all_of(
            _it_is_ours(False),
            _it_is_a_word_argus_knows(True)
        ))


@pytest.mark.unit
def test_an_ownership_nobody_here_declared_is_not_read_as_permission() -> None:
    # The register is the organisation's, not Argus's, and it will grow words -
    # a service another division runs, a vendor a partner resells. Neither
    # default is acceptable: read as ours it sends a restart into an estate
    # nobody authorised, and refused outright it would have one new word
    # anywhere in the register stop Argus reading any of it, so every incident
    # would escalate.
    #
    # So the answer survives, says it is not ours, and keeps the word itself -
    # which is what lets the account of the incident say that the register
    # answered something this system does not recognise, instead of leaving a
    # reader to wonder why a service of their own was out of reach.
    Scenario() \
        .given(unheard_of := a_dependency("shared-with-a-partner")) \
        .when(lambda: unheard_of) \
        .then(all_of(
            _it_is_ours(False),
            _it_is_a_word_argus_knows(False),
            _the_word_the_register_used_survives("shared-with-a-partner")
        ))


def _it_is_ours(expected: bool) -> Assertion[ServiceDependency]:
    def assertion(dependency: ServiceDependency) -> bool:
        if dependency.is_ours is not expected:
            raise AssertionError(
                f"Expected an ownership of [{dependency.ownership}] to report "
                f"is_ours as [{expected}], and it reported "
                f"[{dependency.is_ours}]."
            )

        return True

    return assertion


def _it_is_a_word_argus_knows(expected: bool) -> Assertion[ServiceDependency]:
    def assertion(dependency: ServiceDependency) -> bool:
        if dependency.is_recognised is not expected:
            raise AssertionError(
                f"Expected an ownership of [{dependency.ownership}] to report "
                f"is_recognised as [{expected}], and it reported "
                f"[{dependency.is_recognised}] - so nothing downstream can tell "
                f"a word this system understands from one it does not."
            )

        return True

    return assertion


def _the_word_the_register_used_survives(expected: str) -> Assertion[ServiceDependency]:
    """That the register's own word reaches whoever reads the incident.

    Collapsing it to a flag on the way in would leave the account saying a
    service of the organisation's own was out of Argus's reach, with nothing
    anywhere saying why - and the why is a single word in one register entry
    that somebody has to go and correct.
    """
    def assertion(dependency: ServiceDependency) -> bool:
        if dependency.ownership != expected:
            raise AssertionError(
                f"Expected the register's own word [{expected}] to survive, and "
                f"what came back was [{dependency.ownership}]."
            )

        return True

    return assertion
