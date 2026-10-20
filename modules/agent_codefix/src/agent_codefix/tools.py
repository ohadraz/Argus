"""The repository channels Code-Fix is offered, and what answering one comes to.

Four ways of reading somebody else's source - two searches, a listing and a
read. Each is the read tier's, which serves the Investigator's reads as well:
what a channel says to a model is the server's to declare (MCP, `tools/list`),
so it is written once, beside the code that answers it there. What is held here
is which of them Code-Fix offers for each way a deployment finds source, and
the code that serves a call when the model makes one.

The answering tools are not here. `submit_fix`, `report_nothing_to_change` and
`answer_question` end the conversation rather than feeding it, they retrieve
nothing, and what is written about them is the shape of an answer - so they stay
in `prompting`, beside the brief and the schema that reads them back.
"""

from __future__ import annotations

import logging
from collections.abc import Collection, Mapping, Sequence
from typing import Final

from argus_core.models import CodeSearch, ToolCall, ToolDefinition, ToolResult

from agent_codefix.budget import FixSettings
from agent_codefix.prompting import ANSWER_QUESTION, REPORT_NOTHING_TO_CHANGE, SUBMIT_FIX
from agent_codefix.retrieval import (
    FileLister,
    FileReader,
    MeaningSearcher,
    SourceSearcher,
)

SEARCH_TOOL: Final = "search_repository"
SEARCH_BY_MEANING_TOOL: Final = "search_repository_by_meaning"
LIST_FILES_TOOL: Final = "list_repository_files"
READ_FILE_TOOL: Final = "read_repository_file"

PATH_ARGUMENT: Final = "path"
QUERY_ARGUMENT: Final = "query"
DESCRIPTION_ARGUMENT: Final = "description"

logger = logging.getLogger(__name__)

# The argument every read-tier tool held here is asked at. The ref is the
# branch a fix is cut from, so it is filled in here and never offered.
_REF_ARGUMENT: Final = "ref"


def _held(*names: str) -> Mapping[str, Collection[str]]:
    return {name: frozenset({_REF_ARGUMENT}) for name in names}


# The read tier's tools Code-Fix holds, for each way a deployment finds source,
# in the order they are offered. Both implementations stay present whichever is
# chosen - what configuration decides is what the model is *offered*, not what
# this module can do - so a benchmark run comparing retrievers runs the same
# code either way.
#
# Searching comes first because the opening message tells the model to start
# there, and a list whose order contradicts its instructions is one more thing
# to be resolved by whichever the model is most used to.
READ_TIER_HELD: Final[Mapping[CodeSearch, Mapping[str, Collection[str]]]] = {
    CodeSearch.GREP: _held(SEARCH_TOOL, LIST_FILES_TOOL, READ_FILE_TOOL),
    CodeSearch.MEANING: _held(SEARCH_BY_MEANING_TOOL, LIST_FILES_TOOL, READ_FILE_TOOL),
    CodeSearch.BOTH: _held(
        SEARCH_TOOL, SEARCH_BY_MEANING_TOOL, LIST_FILES_TOOL, READ_FILE_TOOL
    )
}


def tools_for(read_tier: Sequence[ToolDefinition]) -> list[ToolDefinition]:
    """The tools the model is offered, in the order it meets them: the reads
    `read_tier` serves, as the tier declares them, and the three ways to
    answer."""
    return [
        *read_tier,
        SUBMIT_FIX,
        REPORT_NOTHING_TO_CHANGE,
        ANSWER_QUESTION
    ]


def the_answer_to(call: ToolCall,
                  settings: FixSettings,
                  search: SourceSearcher,
                  search_by_meaning: MeaningSearcher,
                  list_files: FileLister,
                  read_file: FileReader) -> ToolResult:
    """One tool call, answered - including when answering it failed.

    A failure comes back as a result the model reads rather than as an
    exception the loop dies on. What it did wrong is usually recoverable in one
    turn, and what it cannot recover from it will simply fail to submit after,
    which is already an answer this loop knows how to report.
    """
    try:
        return ToolResult(
            call_id=call.id,
            content=_ran(
                call, settings, search, search_by_meaning, list_files, read_file
            )
        )
    except Exception as error:
        logger.warning("tool call failed", exc_info=True, extra={"tool": call.name})

        return ToolResult(
            call_id=call.id,
            content=f"{type(error).__name__}: {error}",
            failed=True
        )


def _ran(call: ToolCall,
         settings: FixSettings,
         search: SourceSearcher,
         search_by_meaning: MeaningSearcher,
         list_files: FileLister,
         read_file: FileReader) -> str:
    if call.name == SEARCH_BY_MEANING_TOOL:
        near = search_by_meaning(
            str(call.arguments.get(DESCRIPTION_ARGUMENT, "")),
            settings.github_base_branch
        )

        # Answered in words for the reason the substring channel is, and with
        # more at stake: an empty answer here is ambiguous between an index
        # that holds nothing like this and an index that holds nothing at all,
        # and a model left to guess picks the reading that ends the work.
        return "\n\n".join(near) if near else (
            "no passage in the repository reads like that - try describing the "
            "behaviour differently, or search for an exact string instead"
        )

    if call.name == SEARCH_TOOL:
        found = search(
            str(call.arguments.get(QUERY_ARGUMENT, "")), settings.github_base_branch
        )

        # Said rather than left as an empty answer. A model handed nothing
        # reads it as a tool that failed and tries again with the same query;
        # told the repository does not contain the string, it searches for
        # something else, which is the move that finds the file.
        return "\n".join(found) if found else "no line in the repository matches that"

    if call.name == LIST_FILES_TOOL:
        return "\n".join(list_files(settings.github_base_branch))

    if call.name == READ_FILE_TOOL:
        return read_file(
            str(call.arguments.get(PATH_ARGUMENT, "")), settings.github_base_branch
        )

    return f"there is no tool called {call.name}"
