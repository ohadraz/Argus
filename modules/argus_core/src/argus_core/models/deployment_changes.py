"""What one deployment changed, as the read tier says it.

Here rather than in the read tier because three parties name it: the server that
says it, the client that carries it, and the Investigator that shows the lines
to a model and keeps the rest for the write-up.
"""

from __future__ import annotations

from pydantic import BaseModel


class DeploymentChanges(BaseModel):
    """The lines a model reads about one deployment, and whether they name every
    file its revision differs in from the one deployed before it.

    `lists_every_file` is what lets a reader say of a file the lines do not
    name that it is as it was at the revision compared against - true only
    where nothing was cut off, on either side of the comparison, and every file
    found was named. An answer of no files is one listing every file there is;
    an answer with no comparison behind it - no such deployment, or none before
    it - lists none, and says nothing of any file.

    A field beside the lines rather than a line among them: the model is shown
    the lines, and what a reader may conclude from them is the write-up's to
    say.
    """

    said: list[str]
    lists_every_file: bool
