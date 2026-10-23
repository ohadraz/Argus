"""What one deployment changed, as the read tier says it.

Here rather than in the read tier because three parties name it: the server that
says it, the client that carries it, and the Investigator that shows the lines
to a model and keeps the rest for the write-up.
"""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel


class DeploymentComparison(StrEnum):
    """Whether a deployment was compared against the one deployed before it -
    and, where it was not, why: no deployment has the revision asked about, or
    none came before it in the history."""

    COMPARED = "compared"
    NOT_DEPLOYED = "not-deployed"
    NOTHING_BEFORE_IT = "nothing-before-it"


class DeploymentChanges(BaseModel):
    """The lines a model reads about one deployment, whether they name every
    file its revision differs in from the one deployed before it, and whether
    there was a comparison behind them at all.

    `lists_every_file` is what lets a reader say of a file the lines do not
    name that it is as it was at the revision compared against - true only
    where nothing was cut off, on either side of the comparison, and every file
    found was named. An answer of no files is one listing every file there is;
    an answer with no comparison behind it - no such deployment, or none before
    it - lists none, and says nothing of any file.

    `comparison` is what tells those two apart: only a comparison is a diff,
    and every reader but the model says the others in its own words. Compared
    by default, as every answer carried before it was claimed to be.

    Fields beside the lines rather than lines among them: the model is shown
    the lines, and what a reader may conclude from them is the write-up's to
    say.
    """

    said: list[str]
    lists_every_file: bool
    comparison: DeploymentComparison = DeploymentComparison.COMPARED
