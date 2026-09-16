"""Closes the pull requests Argus opened, and deletes the branches under them.

A demo leaves things behind. Every scenario staged from the shop's console ends
with Code-Fix proposing a fix, and a proposal is a real pull request on a real
repository with a real branch under it - so a morning of rehearsal leaves a
dozen, and the next demo opens number thirteen in front of an audience.

The Target Environment already has a reset for the rest of it: the shop puts its
scenario back, the flags go back to their boot state, the provider forgets what
changed. This is that reset's missing half, and it lives here rather than behind
an endpoint on Argus for a reason that is not convenience. Argus may propose a
fix and may never dispose of one (spec §13). An endpoint that closed pull
requests would be a destructive capability in the one process that must not have
it, reachable by anything that can reach Argus - and the fact that a person
happened to be the caller today is not a property of the system.

So: a script, run by whoever is running the demo. `nox -s stack` calls it on the
way down, and it can be run on its own between two scenarios in one sitting:

    uv run python -m scripts.clean_the_repository

Only Argus's own branches, matched by prefix. A repository has branches that
people are working on, and a cleanup that read "not main" as "mine" would delete
one of those the first time it ran anywhere real.

Never fails the caller. This runs in a teardown, where the interesting failure
is the one that already happened - a cleanup that raised over a pull request
somebody had closed by hand would replace that failure with its own.
"""

from __future__ import annotations

import sys
from typing import Any, Final

import httpx
from argus_core import get_settings

# What Argus names a branch it cuts, and the only thing this deletes. Kept in
# step with `agent_codefix` by being the prefix that module writes rather than a
# pattern that happens to match it today.
ARGUS_BRANCH_PREFIX: Final = "argus/"

REQUEST_TIMEOUT_SECONDS: Final = 15.0

# GitHub's wire vocabulary, named for the fields that carry it.
_NUMBER_FIELD: Final = "number"
_HEAD_FIELD: Final = "head"
_REF_FIELD: Final = "ref"
_STATE_FIELD: Final = "state"
_TITLE_FIELD: Final = "title"
_OPEN_STATE: Final = "open"
_CLOSED_STATE: Final = "closed"

_ACCEPT_HEADER: Final = "application/vnd.github+json"


def main() -> int:
    """Says what it removed, and answers zero whatever happened.

    A teardown's exit code is the session's, so a cleanup that reported its own
    trouble as failure would turn a green demo red for having tidied up
    imperfectly.
    """
    settings = get_settings()

    if not settings.github_repository or not settings.github_token:
        print("no repository configured - nothing to clean")

        return 0

    base = f"{settings.github_api_url}/repos/{settings.github_repository}"
    headers = {
        "Authorization": f"Bearer {settings.github_token}",
        "Accept": _ACCEPT_HEADER
    }

    try:
        with httpx.Client(timeout=REQUEST_TIMEOUT_SECONDS, headers=headers) as github:
            closed = _close_what_argus_proposed(github, base)
            deleted = _delete_what_argus_branched(github, base, closed)
    except Exception as error:
        print(f"could not clean [{settings.github_repository}]: {error!r}")

        return 0

    print(
        f"closed {len(closed)} pull request(s) and deleted {len(deleted)} branch(es) "
        f"on [{settings.github_repository}]"
    )

    return 0


def _close_what_argus_proposed(github: httpx.Client, base: str) -> list[str]:
    """Closes every open pull request Argus opened, and says which branches they were on.

    Closed rather than deleted, because a pull request cannot be deleted at all -
    GitHub has no such call, and the number it was given is spent for good. What
    a reset can restore is the repository's state, never its history.

    By the head branch rather than by the author: the token Argus writes under
    may be a person's, and "everything this credential opened" would sweep up
    pull requests somebody opened themselves.
    """
    answered = github.get(f"{base}/pulls", params={_STATE_FIELD: _OPEN_STATE})
    answered.raise_for_status()

    on_branches: list[str] = []

    for proposal in answered.json():
        branch = proposal.get(_HEAD_FIELD, {}).get(_REF_FIELD, "")

        if not branch.startswith(ARGUS_BRANCH_PREFIX):
            continue

        number = proposal.get(_NUMBER_FIELD)
        closing = github.patch(
            f"{base}/pulls/{number}", json={_STATE_FIELD: _CLOSED_STATE}
        )
        closing.raise_for_status()
        print(f"  closed #{number} {proposal.get(_TITLE_FIELD, '')}")
        on_branches.append(branch)

    return on_branches


def _delete_what_argus_branched(github: httpx.Client,
                                base: str,
                                closed: list[str]) -> list[str]:
    """Deletes every branch Argus cut, whether or not a proposal sat on it.

    Both, because the two come apart: a run that wrote a branch and then failed
    to open the pull request leaves the branch with nothing pointing at it, and
    a cleanup that only followed proposals would never find it.

    A branch already gone is not a failure. Somebody may have deleted it from
    the pull request page, which is the ordinary way, and a reset that refused
    over work already done would be a reset nobody runs twice.
    """
    answered = github.get(f"{base}/branches", params={"per_page": 100})
    answered.raise_for_status()

    mine = {
        _the_name_of(branch)
        for branch in answered.json()
        if _the_name_of(branch).startswith(ARGUS_BRANCH_PREFIX)
    }

    deleted: list[str] = []

    for branch in sorted(mine | set(closed)):
        removing = github.delete(f"{base}/git/refs/heads/{branch}")

        if removing.status_code in (httpx.codes.NO_CONTENT, httpx.codes.OK):
            print(f"  deleted {branch}")
            deleted.append(branch)

    return deleted


def _the_name_of(branch: dict[str, Any]) -> str:
    return str(branch.get("name", ""))


if __name__ == "__main__":
    sys.exit(main())
