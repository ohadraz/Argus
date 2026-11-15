"""Whether the index describes the code that is deployed.

The question every other part of this module asks first. The catch-up pass
asks it to find out whether there is work; retrieval asks it to find out
whether an answer needs a warning on it; Code-Fix asks it to find out what to
tell the model before it reads a single passage.

A comparison rather than a stored verdict, which is the whole reason nothing
here needs a retry counter or a queue of unprocessed notifications. Two strings
either name the same commit or they do not, and a pass that failed leaves them
naming different ones - so the next pass finds the same work waiting without
anybody having recorded that it was owed.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Freshness:
    """What the index describes, against what the repository is at.

    `indexed_sha` is `None` when nothing has been indexed at all. That is the
    absence of a mark rather than a mark that happens to differ, and the two are
    kept apart because the work they call for is not the same: an empty index is
    a backfill, where one that has fallen behind is the handful of paths a push
    named.
    """

    indexed_sha: str | None
    deployed_sha: str

    @property
    def is_current(self) -> bool:
        """Whether what was indexed is what is deployed.

        An index that was never built is not current, however the comparison is
        spelled - `None` is not the deployed commit, and answering otherwise
        would report an empty index as describing the service.
        """
        return self.indexed_sha == self.deployed_sha

    @property
    def has_never_been_indexed(self) -> bool:
        """Whether there is anything to compare against at all.

        Asked apart from `is_current` because both answers are "there is work",
        and only this one says the work is the whole repository.
        """
        return self.indexed_sha is None

    @property
    def notice(self) -> str | None:
        """What a reader has to be told before trusting what it retrieves.

        `None` when the index is current, which is the point of answering here
        rather than leaving each caller to ask `is_current` first. Retrieval
        prefixes this onto its answer and Code-Fix opens with it; two callers
        each deciding when to stay quiet is two places for a warning to outlive
        the condition it was about.

        Two different notices, because two different things are wrong. An index
        that has fallen behind still answers, and what it answers may simply be
        old - so the commits are named, and a reader that knows both can judge
        whether the gap matters. An index that was never built answers nothing
        at all, and telling that reader its results may be out of date would
        have it read an empty answer as a fact about the repository.
        """
        if self.is_current:
            return None

        if self.has_never_been_indexed:
            return (
                "nothing has been indexed for this repository yet, so "
                "retrieval by meaning will find nothing whatever the source "
                "contains"
            )

        return (
            f"the passages retrievable here describe commit "
            f"{self.indexed_sha}, and the deployed branch is at "
            f"{self.deployed_sha} - code that changed in between may not be "
            f"findable by meaning yet"
        )
