"""The mypy plugin that checks `model_copy(update={...})`, asked through mypy.

The plugin's failure is silent: a hook that stops firing - a suffix mypy no
longer names, a base it no longer reports, an API renamed under it - leaves the
typecheck green and every update unchecked again, behind a check that still
looks present. So each case runs mypy, with the repository's own configuration,
over a few lines that either break the rule or keep it, and reads what mypy
said.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from argus_testkit import Assertion, Scenario
from mypy import api

THE_CONFIGURATION = Path(__file__).resolve().parents[2] / "pyproject.toml"

# A model with a field of its own and one it inherits, so that a key declared on
# a base is asked about as well as one declared on the model itself.
SOME_MODELS = '''
from pydantic import BaseModel


class Buki(BaseModel):
    named: str | None = None


class Kuki(Buki):
    rounds: int = 0


some_kuki = Kuki()
'''


@pytest.mark.unit
def test_a_key_the_model_has_no_field_for_fails_the_typecheck() -> None:
    # The case the plugin exists for: a field renamed in the model, and an
    # update still naming it, which pydantic drops without a word.
    Scenario() \
        .given(an_update := SOME_MODELS + 'some_kuki.model_copy(update={"kukis": 1})\n') \
        .when(lambda: _what_mypy_says_of(an_update)) \
        .then(_it_failed_saying('"Kuki" has no field "kukis"'))


@pytest.mark.unit
def test_a_value_of_the_wrong_type_fails_the_typecheck() -> None:
    # Pydantic stores it as given, so a field typed as a number holds a string
    # and the code reading it finds out at run time, if at all.
    Scenario() \
        .given(an_update := SOME_MODELS + 'some_kuki.model_copy(update={"rounds": "one"})\n') \
        .when(lambda: _what_mypy_says_of(an_update)) \
        .then(_it_failed_saying('Field "rounds" of "Kuki" is "int"'))


@pytest.mark.unit
def test_an_update_the_model_can_hold_passes_the_typecheck() -> None:
    # Both fields, the inherited one among them, with values of their own types.
    # A plugin that refused this would be refused in turn, and switched off.
    Scenario() \
        .given(an_update := SOME_MODELS
               + 'some_kuki.model_copy(update={"rounds": 2, "named": "kuki"})\n') \
        .when(lambda: _what_mypy_says_of(an_update)) \
        .then(_it_passed())


def _what_mypy_says_of(source: str) -> tuple[str, int]:
    """What mypy prints about `source`, and the status it exits with."""
    said, dont_care_errors, status = api.run(
        ["--config-file", str(THE_CONFIGURATION), "-c", source]
    )

    return said, status


def _it_failed_saying(expected: str) -> Assertion[tuple[str, int]]:
    def assertion(answer: tuple[str, int]) -> bool:
        said, status = answer

        if status == 0 or expected not in said:
            raise AssertionError(
                f"Expected the typecheck to fail saying [{expected}], it exited "
                f"[{status}] and said [{said}]."
            )

        return True

    return assertion


def _it_passed() -> Assertion[tuple[str, int]]:
    def assertion(answer: tuple[str, int]) -> bool:
        said, status = answer

        if status != 0:
            raise AssertionError(
                f"Expected the typecheck to pass, it exited [{status}] and said "
                f"[{said}]."
            )

        return True

    return assertion
