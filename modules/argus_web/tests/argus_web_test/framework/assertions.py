"""What a page had to say, and what an endpoint had to answer.

Read against the rendered document rather than the view's return value, on
purpose: what a reader gets is the HTML, and a template that stopped emitting a
field would leave every assertion about the view's data passing.
"""

from __future__ import annotations

from http import HTTPStatus as HttpStatus

import httpx
from argus_testkit import Assertion

from argus_web_test.framework.reading import attribute

# What a live page includes while there is more to come, and leaves out once
# there is not. Named here because two suites look for it and a literal copied
# into both is a literal one of them can get wrong.
POLLS_FOR_MORE = "hx-trigger"


def the_page_says(text: str) -> Assertion[str]:
    def assertion(page: str) -> bool:
        if text not in page:
            raise AssertionError(f"Expected the page to say [{text}], it did not.")

        return True

    return assertion


def the_page_links_to(href: str) -> Assertion[str]:
    def assertion(page: str) -> bool:
        if f'href="{href}"' not in page:
            raise AssertionError(f"Expected the page to link to [{href}], it did not.")

        return True

    return assertion


def the_page_shows(name: str, *values: str) -> Assertion[str]:
    """Exactly these values of one `data-` attribute, in this order.

    Order and completeness together, because both are claims the page makes: a
    reader takes the first row as the newest, and an extra row nobody expected
    is as wrong as a missing one.
    """
    def assertion(page: str) -> bool:
        shown = attribute(name, page)

        if shown != list(values):
            raise AssertionError(
                f"Expected [{name}] to be {list(values)}, got {shown}."
            )

        return True

    return assertion


def the_page_keeps_asking() -> Assertion[str]:
    """That the page will come back for more of its own accord.

    The half of a live page that no rendered value shows: an incident still
    being worked has to poll, and a page that stopped would sit there looking
    correct and never update again.
    """
    def assertion(page: str) -> bool:
        if POLLS_FOR_MORE not in page:
            raise AssertionError("Expected the page to keep asking for more, it did not.")

        return True

    return assertion


def the_response_was(expected: HttpStatus) -> Assertion[httpx.Response]:
    """The status an endpoint answered with.

    Named for the response rather than for the answer, because `the_answer_was`
    in `argus_testkit` is a value equality and this is not one - it reaches
    into the response for a status and reports the body when it disagrees,
    which is the part that says why.
    """
    def assertion(response: httpx.Response) -> bool:
        if response.status_code != expected:
            raise AssertionError(
                f"Expected [{expected}], got [{response.status_code}]: {response.text}."
            )

        return True

    return assertion
