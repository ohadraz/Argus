"""The repository channels Code-Fix is offered, and what answering one comes to.

Four ways of reading somebody else's source - two searches, a listing and a
read - each said twice over: once as the offer the model chooses from, and once
as the code that serves the call when it chooses. Both halves live here because
they are one decision. A channel whose description promises something its
answering does not do is the one bug no schema catches, and the two drifting apart
is what putting them in separate modules invites.

The submission tools are not here. `submit_fix` and `report_nothing_to_change`
end the conversation rather than feeding it, they retrieve nothing, and what is
written about them is the shape of an answer - so they stay in `prompting`, beside
the brief and the schema that reads them back.
"""

from __future__ import annotations

import logging
from typing import Final

from argus_core.models import CodeSearch, ToolCall, ToolDefinition, ToolResult

from agent_codefix.budget import FixSettings
from agent_codefix.prompting import REPORT_NOTHING_TO_CHANGE, SUBMIT_FIX
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

SEARCH = ToolDefinition(
    name=SEARCH_TOOL,
    description=(
        "Find where something appears in the service's source. Answers with "
        "every matching line as 'path:line: text'. START HERE: the "
        "investigation has already named the cause, so search for it - the "
        "flag, the function, the message from the log line - and the answer "
        "tells you which files to read. Plain text, not a regular expression."
    ),
    properties={
        QUERY_ARGUMENT: {
            "type": "string",
            "description": (
                "The text to look for. Something distinctive from the cause - "
                "a flag name, a function name, an error message."
            )
        }
    },
    required=[QUERY_ARGUMENT]
)

LIST_FILES = ToolDefinition(
    name=LIST_FILES_TOOL,
    description=(
        "List every file in the service's repository, as paths from its root. "
        "A fallback for when searching found nothing and you need to see the "
        f"shape of the repository - prefer {SEARCH_TOOL}, which tells you "
        "which file to open rather than leaving you to guess from names."
    ),
    properties={},
    required=[]
)

# Said here rather than in the brief, because the first sentence of this
# description is what was holding the model to one file at a time. It reads as
# a limit where a unit was meant, and no instruction elsewhere outranks a tool
# telling you what it does. Measured: one file in 59 of 88 turns, never more
# than four, though every parallel call is answered in a single reply.
#
# The reason travels with it. Turns are what the re-send is quadratic in, so a
# turn spent on one file is not one round trip's worth of waste but one file's
# worth on every turn after it - and a model told only "you may" batches
# timidly, as this one already did.
READ_FILE = ToolDefinition(
    name=READ_FILE_TOOL,
    description=(
        "Read one file's entire contents. Call it several times in the same "
        "turn when you want several files - every result comes back together, "
        "and a turn spent on one file re-sends everything you have read so "
        "far. Read a file before you rewrite it - what you submit replaces "
        "what is there, so a file you did not read is a file you are "
        "overwriting blind."
    ),
    properties={
        PATH_ARGUMENT: {
            "type": "string",
            "description": "The file's path from the repository root."
        }
    },
    required=[PATH_ARGUMENT]
)

SEARCH_BY_MEANING = ToolDefinition(
    name=SEARCH_BY_MEANING_TOOL,
    description=(
        "Find code by describing what it does, when you have no exact text to "
        "search for. Answers with passages of the service's source - each one "
        "'path:start-end' and the lines themselves - nearest in meaning to "
        f"your description. Use this where {SEARCH_TOOL} cannot help: the "
        "investigation described a behaviour ('the discount is divided by a "
        "count that can be zero') and the repository may not contain any of "
        "those words. Describe the behaviour and the mistake, not an "
        "identifier. Worth using alongside the other search rather than "
        "instead of it - one matches characters, this matches meaning."
    ),
    properties={
        DESCRIPTION_ARGUMENT: {
            "type": "string",
            "description": (
                "What the code you are looking for does, in a sentence - the "
                "behaviour and what is wrong with it, as you would describe "
                "it to another engineer."
            )
        }
    },
    required=[DESCRIPTION_ARGUMENT]
)


def tools_for(settings: FixSettings) -> list[ToolDefinition]:
    """The tools this deployment offers the model, in the order it meets them.

    Both implementations stay present whichever is chosen - what configuration
    decides is what the model is *offered*, not what this module can do. A
    channel switched off is one definition missing from a list, so a benchmark
    run comparing retrievers is running the same code either way.

    Searching comes first because the opening message tells the model to start
    there, and a list whose order contradicts its instructions is one more
    thing to be resolved by whichever the model is most used to.
    """
    searching = {
        CodeSearch.GREP: [SEARCH],
        CodeSearch.MEANING: [SEARCH_BY_MEANING],
        CodeSearch.BOTH: [SEARCH, SEARCH_BY_MEANING]
    }

    return [
        *searching[settings.code_search],
        LIST_FILES,
        READ_FILE,
        SUBMIT_FIX,
        REPORT_NOTHING_TO_CHANGE
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
