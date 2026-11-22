"""A person telling Argus how an incident ended, and where they said it.

Where is two things: the part the door plays - Argus's own page, a paging tool,
an incident's thread - and, for a platform, which one, by the name its adapter
gives it. The second is what a reader is told the report came from, so a report
through a platform that names none, or through Argus's page that names one,
would tell a reader something nobody established.
"""

from __future__ import annotations

import pytest
from argus_testkit import Scenario, an_error_was_raised, attempting, the_answer_was
from core.models import Report, ReportChannel
from pydantic import ValidationError

DONT_CARE_PERSON = "some person"
SOME_PLATFORM = "some-platform"
# A platform's name left empty, which a reader would be told as "from ".
NO_NAME = ""


@pytest.mark.unit
@pytest.mark.parametrize("through", [ReportChannel.ON_CALL_PLATFORM, ReportChannel.CHAT_PLATFORM])
def test_a_report_through_a_platform_carries_the_platform_s_name(through: ReportChannel) -> None:
    Scenario() \
        .when(lambda: Report(by=DONT_CARE_PERSON, channel=through,
                             platform=SOME_PLATFORM).platform) \
        .then(the_answer_was(SOME_PLATFORM))


@pytest.mark.unit
@pytest.mark.parametrize("through", [ReportChannel.ON_CALL_PLATFORM, ReportChannel.CHAT_PLATFORM])
@pytest.mark.parametrize("platform", [None, NO_NAME], ids=["none", "an-empty-name"])
def test_a_report_through_a_platform_naming_none_is_refused(through: ReportChannel,
                                                            platform: str | None) -> None:
    # Where the person was is what a reader is told, and "a platform" is not a
    # place anybody can go to find them.
    Scenario() \
        .when(attempting(lambda: Report(by=DONT_CARE_PERSON, channel=through,
                                        platform=platform))) \
        .then(an_error_was_raised(ValidationError))


@pytest.mark.unit
def test_a_report_through_argus_s_own_page_names_no_platform() -> None:
    Scenario() \
        .when(lambda: Report(by=DONT_CARE_PERSON, channel=ReportChannel.ARGUS_UI).platform) \
        .then(the_answer_was(None))


@pytest.mark.unit
@pytest.mark.parametrize("platform", [SOME_PLATFORM, NO_NAME], ids=["a-name", "an-empty-name"])
def test_a_report_through_argus_s_own_page_naming_a_platform_is_refused(platform: str) -> None:
    # A report typed into Argus's page passed through no platform, and saying
    # one would send a reader looking for the person somewhere they never were.
    Scenario() \
        .when(attempting(lambda: Report(by=DONT_CARE_PERSON, channel=ReportChannel.ARGUS_UI,
                                        platform=platform))) \
        .then(an_error_was_raised(ValidationError))
