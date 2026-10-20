"""What a model is told of each read-tier tool it may be offered.

The server owns a tool's definition (MCP, `tools/list`) and an agent offers
what it declares, so these are the only words a model reads about a tool -
written for the model, after Anthropic's "Define tools": what the tool does,
when it is the one to reach for, and what it will not say. The docstrings
beside each registration are for whoever maintains the server, and stay there.

Each argument's words are its own, beside the argument. An argument the agent
fills in itself never appears in the tool's prose: it is taken out of what the
model sees, and prose describing it would describe something the model cannot
pass.

Some of this is one agent's advice, because one agent holds the tool: Code-Fix
alone reads the repository, and the Investigator alone the deployment and the
register. Whoever offers a tool to another agent next reads its words first.

One description is shared by every agent and every way of finding source that
offers the tool, so it names another tool only where each of them offers that
one too. Advice to "prefer search_repository" read in a deployment that
searches by meaning alone points the model at a tool it does not have.
"""

from __future__ import annotations

from typing import Final

SERVICE_DEPENDENCIES: Final = (
    "What this service calls, what each of those is for, and whether the "
    "organisation owns it. Worth reading whenever the time a request "
    "spends, or the failure it reports, points at something this service "
    "does not run - because the response depends entirely on whose that "
    "something is, and nothing else you can retrieve says. A host name "
    "will not tell you: an internal-looking name is internal-looking "
    "because somebody chose the spelling. Takes no arguments; it answers "
    "about the service this incident is about."
)

# Names the Investigator's own change channel, the one place its revision is
# copied from.
WHAT_A_DEPLOYMENT_CHANGED: Final = (
    "What one deployment changed: the files that differ from the revision "
    "deployed before it, and the change made to each. Read this before "
    "saying which of two causes a deployment was - a deployment that "
    "shipped bad code and one that shipped a broken configuration value "
    "arrive identically, move the same signals, and are put right the same "
    "way, and the only thing that separates them is what was in the "
    "commit. Nothing else you can retrieve says: the path a deployment "
    "syncs from is where its manifests live, and is the same directory "
    "whatever the commit touched. Takes the deploy's own revision, exactly "
    "as get_changes reported it."
)
WHAT_A_DEPLOYMENT_CHANGED_REVISION: Final = (
    "The deployment's revision, copied from the change this asks "
    "about. What it is compared against is not yours to name - the "
    "revision deployed before it is in the deployment history, "
    "which you cannot see."
)

ROLLOUT_STATE: Final = (
    "Whether the deployment this service is running has finished "
    "arriving: how many replicas are on the revision being rolled out, "
    "how many are still on the one before it, and whether the rolling "
    "update is paused. Read this before saying a deployment at the onset "
    "is the fault - a revision that is wrong and a revision that reached "
    "only half the fleet arrive identically in the change channel, and "
    "the second fails only the requests that cross between the two "
    "versions now serving. Nothing else you can retrieve says: a deploy "
    "history records syncs that finished, and a rollout that has not "
    "finished is not in it. A deployment that has converged is an answer "
    "worth having too - it rules the split out. Takes no arguments; it "
    "answers about the service this incident is about."
)

SEARCH_REPOSITORY: Final = (
    "Find where something appears in the service's source. Answers with "
    "every matching line as 'path:line: text'. START HERE: the "
    "investigation has already named the cause, so search for it - the "
    "flag, the function, the message from the log line - and the answer "
    "tells you which files to read. Plain text, not a regular expression."
)
SEARCH_REPOSITORY_QUERY: Final = (
    "The text to look for. Something distinctive from the cause - "
    "a flag name, a function name, an error message."
)

LIST_REPOSITORY_FILES: Final = (
    "List every file in the service's repository, as paths from its root. "
    "A fallback for when searching found nothing and you need to see the "
    "shape of the repository - prefer a search, which tells you which file "
    "to open rather than leaving you to guess from names. A "
    "repository that could not be listed whole is reported as a failure, "
    "never as a shorter list."
)

# Code-Fix's advice, and measured there: the first sentence of the old wording
# held the model to one file a turn - one file in 59 of 88 turns, never more
# than four - though every parallel call is answered in a single reply. The
# reason travels with it: turns are what the re-send is quadratic in.
READ_REPOSITORY_FILE: Final = (
    "Read one file's entire contents. Call it several times in the same "
    "turn when you want several files - every result comes back together, "
    "and a turn spent on one file re-sends everything you have read so "
    "far. Read a file before you rewrite it - what you submit replaces "
    "what is there, so a file you did not read is a file you are "
    "overwriting blind."
)
READ_REPOSITORY_FILE_PATH: Final = "The file's path from the repository root."

SEARCH_REPOSITORY_BY_MEANING: Final = (
    "Find code by describing what it does, when you have no exact text to "
    "search for. Answers with passages of the service's source - each one "
    "'path:start-end' and the lines themselves - nearest in meaning to "
    "your description. Use this where searching for exact text cannot help: "
    "the investigation described a behaviour ('the discount is divided by a "
    "count that can be zero') and the repository may not contain any of "
    "those words. Describe the behaviour and the mistake, not an "
    "identifier. Where you can also search for exact text, do both rather "
    "than one instead of the other - one matches characters, this matches "
    "meaning."
)
SEARCH_REPOSITORY_BY_MEANING_DESCRIPTION: Final = (
    "What the code you are looking for does, in a sentence - the "
    "behaviour and what is wrong with it, as you would describe "
    "it to another engineer."
)

# The arguments each tool's caller fills in itself, described for whoever
# reads the schema; the model is never shown them.
THE_SERVICE: Final = "The service the incident is about, as the register and the platform name it."
THE_REF: Final = "The branch or commit to read the repository at."
