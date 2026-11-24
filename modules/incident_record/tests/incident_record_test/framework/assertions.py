"""Assertions more than one of this package's suites makes."""

from __future__ import annotations

from argus_testkit import Assertion
from core.models import IncidentStatus
from pydantic import BaseModel

from incident_record_test.framework.transactions import Seen


def the_account_was_written_inside_the_change(seen: list[Seen],
                                              status: IncidentStatus) -> Assertion[object]:
    """That the account of a change to `status` was written once, inside the
    change's own transaction: seen there as `status`, and from anywhere else as
    still acknowledged."""
    def assertion(_ended: object) -> bool:
        expected = [Seen(inside=status, outside=IncidentStatus.ACKNOWLEDGED)]

        if seen != expected:
            raise AssertionError(
                f"Expected the account to be written once, inside the change - seen "
                f"as [{status}] where it was written and still as "
                f"[{IncidentStatus.ACKNOWLEDGED}] anywhere else; it was written "
                f"{seen}."
            )

        return True

    return assertion


def each_field_of(model: type[BaseModel]) -> Assertion[tuple[str, ...]]:
    """That the columns name each of `model`'s fields once, and nothing else.

    A field missing is one never written; a column the model has no field for
    is one no read can fill; and one named twice is written twice in the same
    statement, which the database refuses.
    """
    def assertion(columns: tuple[str, ...]) -> bool:
        fields = set(model.model_fields)
        missing = sorted(fields - set(columns))
        unknown = sorted(set(columns) - fields)
        repeated = sorted({column for column in columns if columns.count(column) > 1})

        if missing or unknown or repeated:
            raise AssertionError(
                f"Expected a column for each of [{model.__name__}]'s fields, once; "
                f"missing {missing}, with no field {unknown}, named more than once "
                f"{repeated}."
            )

        return True

    return assertion
