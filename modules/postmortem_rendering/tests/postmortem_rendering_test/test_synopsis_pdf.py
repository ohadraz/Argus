"""The executive synopsis printed: the file its Slack message links to, saying
every part in the order the synopsis reads, with the full postmortem a click
away.

Each case prints one synopsis and reads its text back, whitespace collapsed - a
line the PDF wrapped is still the line it was - and checks what the file says;
where a link is the claim, where it lands.
"""

from __future__ import annotations

import io
from typing import Any

import pytest
from argus_testkit import Assertion, Scenario, all_of
from postmortem_rendering.synopsis_pdf import synopsis_as_pdf
from pypdf import PdfReader

from postmortem_rendering_test.framework.synopses import (
    SOME_POSTMORTEM_ADDRESS,
    a_synopsis_read,
    the_parts_missing_or_out_of_order,
)


@pytest.mark.unit
def test_every_part_is_printed_in_the_order_the_synopsis_reads() -> None:
    Scenario() \
        .when(
            lambda: synopsis_as_pdf(a_synopsis_read())
        ) \
        .then(
            _it_says_every_part_in_order()
        )


@pytest.mark.unit
def test_the_full_postmortem_opens_from_its_address() -> None:
    Scenario() \
        .when(
            lambda: synopsis_as_pdf(a_synopsis_read())
        ) \
        .then(
            _it_links_out_to([SOME_POSTMORTEM_ADDRESS])
        )


@pytest.mark.unit
def test_no_postmortem_is_offered_where_no_address_is_configured() -> None:
    Scenario() \
        .when(
            lambda: synopsis_as_pdf(a_synopsis_read(postmortem_at=None))
        ) \
        .then(all_of(
            _it_does_not_say("Full postmortem"),
            _it_links_out_to([])
        ))


def _the_text_of(pdf: bytes) -> str:
    return " ".join(" ".join(page.extract_text()
                             for page in PdfReader(io.BytesIO(pdf)).pages).split())


def _it_says_every_part_in_order() -> Assertion[bytes]:
    def assertion(pdf: bytes) -> bool:
        said = _the_text_of(pdf)
        missing = the_parts_missing_or_out_of_order(said)
        if missing:
            raise AssertionError(
                f"Expected every part in order, missing or out of order: {missing}, "
                f"in:\n{said}")

        return True

    return assertion


def _it_does_not_say(unexpected: str) -> Assertion[bytes]:
    def assertion(pdf: bytes) -> bool:
        said = _the_text_of(pdf)
        if unexpected in said:
            raise AssertionError(f"Expected nothing of [{unexpected}] said, in:\n{said}")

        return True

    return assertion


def _it_links_out_to(expected: list[str]) -> Assertion[bytes]:
    def assertion(pdf: bytes) -> bool:
        links: list[Any] = [annotation.get_object()["/A"]["/URI"]
                            for page in PdfReader(io.BytesIO(pdf)).pages
                            for annotation in page.get("/Annots", [])
                            if "/URI" in annotation.get_object().get("/A", {})]
        if links != expected:
            raise AssertionError(f"Expected the file to link out to {expected}, got {links}.")

        return True

    return assertion
