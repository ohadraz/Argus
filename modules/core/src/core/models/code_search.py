from __future__ import annotations

from enum import StrEnum


class CodeSearch(StrEnum):
    """Which ways of finding code in the repository this deployment has.

    Not only what a model is offered: it decides whether an index is built at
    all, whether the read tier opens a store, and whether the tool exists to
    be called. A deployment set to `GREP` does none of that work rather than
    doing it for nobody.

    Named for what is being chosen rather than for the tier it is served from,
    because `RetrievalChannel` next door is the investigation's three sources
    of evidence and these are two ways of reading one repository. One letter
    between two kernel names meaning different things is a name nobody can use
    confidently.

    `BOTH` is the production setting and not a fallback for "unsure": the
    model is handed both tools and chooses per question, which is the decision
    it is best placed to make. A cause that has a name is found faster by
    grep, and one that only has a description is found at all by meaning.

    The single channels exist for the benchmark (§21). Comparing two
    retrievers means running each alone over the same incidents, which is only
    possible if the choice can be taken away from the model.
    """

    GREP = "grep"
    MEANING = "meaning"
    BOTH = "both"
