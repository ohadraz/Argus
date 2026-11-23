"""A receipt for every read Code-Fix makes (spec §4 principle 6).

Every call out of the process is written to the replay log, with what was asked
and what came back, so a run can be examined later without reaching the
repository again. Code-Fix reads the repository in two ways - when the model
asks, and on its own: the listing and the branch's history for the opening, the
index's freshness, the code outside a patch, and the files as they ran - and
each is a call to the read tier all the same.

So the receipt is kept around the read rather than at each place that asks:
one place every read passes through, as the Investigator's dispatcher is for
its channels, where seven places would be seven chances to forget. A read that
raised leaves none, since nothing was read; and a name the model invented never
reaches a read at all.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Final

from core.replay import CallType, Replay
from pydantic import BaseModel

# The read tier's names for the three reads Code-Fix makes that are never
# offered to its model. The other four are offered, and named in `tools`.
CONTAINS_TOOL: Final = "branch_contains_revision"
INDEX_FRESHNESS_TOOL: Final = "get_repository_index_freshness"
CODE_OUTSIDE_TOOL: Final = "get_code_outside_the_patch"

# And the arguments those three are asked by that the four offered are not.
BRANCH_ARGUMENT: Final = "branch"
REVISION_ARGUMENT: Final = "revision"
FILES_ARGUMENT: Final = "files"


def receipted[**P, R](replay: Replay,
                      tool: str,
                      read: Callable[P, R],
                      *names: str) -> Callable[P, R]:
    """`read`, keeping a receipt in `replay` for each answer it returns.

    Filed under the read tier's name for it (`tool`), with the arguments under
    the names the tier asks them by (`names`, in the order `read` takes them)
    and the answer as it came back. Written after the read returns, so a read
    that raised writes nothing; and the receipt cannot fail the read - a
    recorder that could not write costs the log a row and nothing else
    (`core.replay.record`).
    """
    def receipting(*args: P.args, **kwargs: P.kwargs) -> R:
        answer = read(*args, **kwargs)
        replay.record(
            call_type=CallType.MCP,
            target=tool,
            request={"arguments": {**dict(zip(names, args, strict=False)), **kwargs}},
            response={"answer": _as_recorded(answer)}
        )

        return answer

    return receipting


def _as_recorded(answer: object) -> object:
    """An answer as the log holds it: a model as its JSON, anything else as it is."""
    return answer.model_dump(mode="json") if isinstance(answer, BaseModel) else answer
