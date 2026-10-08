"""Everything about one incident Code-Fix is told before it reads anything.

This incident, and nothing standing. What is always true of fixing a fault - that
a mitigation has probably hidden the symptom, that the change which exposed a
fault is not the fault, that submitting nothing needs a reason - is
`STANDING_BRIEF`, and it travels as the request's `system`. It is the same every
time, so it belongs where the same thing every time can be read back from cache
instead of re-sent and re-billed once per incident.

Apart from the loop because it is written for a reader rather than executed: every
paragraph here is a decision about what a model is told, and the loop's business is
what happens to what it says back.
"""

from __future__ import annotations

import logging

from argus_core.models import CodeSearch, FailureMode, Hypothesis

from agent_codefix.budget import FixSettings
from agent_codefix.prompting import SUBMIT_TOOL_NAME
from agent_codefix.retrieval import FileLister, IndexNotice
from agent_codefix.tools import SEARCH_BY_MEANING_TOOL, SEARCH_TOOL

logger = logging.getLogger(__name__)


def what_it_concluded(hypothesis: Hypothesis | None) -> str:
    """The finding in a sentence, or that there was none.

    Said rather than left blank, because the agent is asked either way: a walk
    that reached here having concluded nothing is still worth reading the code
    over, and "I looked and found nothing" is a different answer from "I never
    looked". An empty line after "the investigation concluded" reads as the
    second while claiming to be the first.

    Public because the proposal says it too. The pull request a person reads
    names the conclusion the fix answers, and two accounts of how a missing
    hypothesis is phrased would eventually disagree - in the one place where
    disagreeing is visible to whoever has to merge it.
    """
    if hypothesis is None:
        return "nothing - no cause was identified, so read the code on its own terms"

    return hypothesis.summary


def the_opening_message(hypothesis: Hypothesis | None,
                        settings: FixSettings,
                        index_notice: IndexNotice,
                        list_files: FileLister) -> str:
    """The first thing the model is sent, built for this incident alone.

    Assembled rather than templated, because three of its paragraphs are
    conditional on what this deployment can do and what the investigation
    actually found - and an empty heading tells a model there is something it has
    failed to see.
    """
    return "\n".join([
        "An incident has been investigated and traced to a cause in this "
        "service's code. Your job is to fix that cause permanently.",
        "",
        f"What the investigation concluded: {what_it_concluded(hypothesis)}",
        *_and_what_it_rests_on(hypothesis),
        *_and_what_it_already_wrote(hypothesis),
        *_what_the_repository_holds(settings, list_files),
        *_what_is_known_about_the_index(settings, index_notice),
        "",
        f"{_how_to_start_looking(settings)} Then call {SUBMIT_TOOL_NAME} with "
        f"every file you are changing, in full."
    ])


def _and_what_it_already_wrote(hypothesis: Hypothesis | None) -> list[str]:
    """That this fault left a residue, for the one mode where it does.

    Every other mode is over when the cause is: a flag goes back, a revision is
    returned, and what was served wrongly is served again correctly. This one
    is not. The patch stops the next wrong value and every value already stored
    stays wrong, so a pull request carrying only the patch closes an incident
    while the damage stays in the rows.

    Said rather than left to be inferred. What the model is looking at is a
    write path with a field update missing, and nothing in that code says how
    many rows went through it - a model asked to work out for itself that a
    residue exists would be reasoning from evidence it was never shown.

    Both in one request, because they are one change: a reviewer approving the
    fix is approving what has to happen to the data behind it. And proposed
    only - running it is a rewrite of stored data, which is irreversible and
    outside what Argus may do unasked (§13).
    """
    if hypothesis is None or hypothesis.failure_mode != FailureMode.SILENT_DATA_CORRUPTION:
        return []

    return [
        "",
        "This fault wrote wrong values before anybody noticed, and they are "
        "still wrong: the patch stops the next one and repairs none of the "
        "ones already written. So submit a second file beside the fix - a "
        "one-off script that reads the records the fault got wrong and puts "
        "them right - and say in your explanation that it has not been run "
        "and that a person has to run it."
    ]


def _and_what_it_rests_on(hypothesis: Hypothesis | None) -> list[str]:
    """The evidence behind the conclusion, quoted rather than summarised.

    The summary says what broke; the evidence says where. This service's error
    boundary records the innermost frame, so one of these lines is a log line
    naming the file and the line the fault was raised on - and an agent handed
    only the sentence goes searching for a location it was already holding.

    Quoted as the investigation wrote them, because they are quotations: a log
    line restated in the model's own words is no longer something it can search
    the repository for.

    Empty where the investigation recorded none, and empty is right - a heading
    over nothing invites the model to wonder what it is missing.
    """
    if hypothesis is None or not hypothesis.supporting_evidence:
        return []

    return [
        "",
        "What that rests on:",
        *(f"  - {found.claim}" for found in hypothesis.supporting_evidence)
    ]


def _how_to_start_looking(settings: FixSettings) -> str:
    """Which search to reach for when the conclusion names no file to open.

    A fallback rather than an opening move. It said "start by searching" once,
    unconditionally, and the model did as it was told even where the sentence
    above already carried the file and the line - then read every candidate
    the search returned, one round trip each. Where to begin is the brief's to
    say now; what this answers is which tool, and only for the case where
    there is genuinely nothing named to begin from.

    Named in terms of the tools this deployment actually offers, because
    pointing a model at a search it was not given is the one way to make an
    opening message worse than none.
    """
    if settings.code_search is CodeSearch.MEANING:
        return (
            f"If the conclusion names no file, describe the broken behaviour and "
            f"{SEARCH_BY_MEANING_TOOL} for it - the answer is the passages "
            f"nearest that description."
        )

    if settings.code_search is CodeSearch.GREP:
        return (
            f"If the conclusion names no file, take what it does name - the flag, the "
            f"function, the message - and {SEARCH_TOOL} for it."
        )

    return (
        f"If the conclusion names no file, {SEARCH_TOOL} for what it does name "
        f"- the flag, "
        f"the function, the message - or, where it describes a behaviour "
        f"instead, {SEARCH_BY_MEANING_TOOL} with that description."
    )


def _what_the_repository_holds(settings: FixSettings,
                               list_files: FileLister) -> list[str]:
    """Every path in the repository, handed over rather than left to be asked for.

    Asked once before the conversation starts, as the index notice is. The
    model called `list_repository_files` first in seven of eleven recorded
    walks and not at all in the other four, so this replaces a round trip about
    two thirds of the time and costs some sixty tokens against a prompt already
    carrying fourteen thousand.

    Here rather than in the standing brief, though every incident wants it: the
    listing changes whenever the repository does, and a `system` block that
    varied per incident would invalidate the cached prefix - for every agent,
    not only this one - each time it varied.

    Empty for an empty listing, for the reason the evidence is: a heading over
    nothing tells the model there is something it has failed to see - and empty
    for a listing that could not be fetched at all, which is the same sentence
    to the model and a very different one to the walk. This call is made while
    the message is being built, before the conversation exists, and the walk
    reads anything escaping `propose_fix` as "no fix could be proposed". So a
    raise here would spend the whole attempt on one flaky call, where the same
    failure a turn later costs a single tool result and a model that reads it.
    """
    try:
        held = list_files(settings.github_base_branch)
    except Exception:
        logger.warning("repository could not be listed", exc_info=True)

        return []

    if not held:
        return []

    return ["", "The repository holds:", *(f"  {path}" for path in held)]


def _what_is_known_about_the_index(settings: FixSettings,
                                   index_notice: IndexNotice) -> list[str]:
    """What the model has to know about searching by meaning before it does.

    Empty when the index describes the commit being fixed, which is the
    ordinary state: a warning printed every run is a warning nobody reads, and
    that is how the run where it was true goes unnoticed.

    Not asked at all where the channel is off. The answer would be true and
    about a tool the model does not have, which is a paragraph spent teaching
    it to distrust something it cannot use.
    """
    if settings.code_search is CodeSearch.GREP:
        return []

    notice = index_notice(settings.github_base_branch)

    return ["", notice] if notice else []
