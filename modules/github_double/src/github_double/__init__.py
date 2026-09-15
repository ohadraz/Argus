"""A stand-in for the part of GitHub's REST API that Argus talks to.

Here for one reason: `e2e_replay` is the run CI does on every push, and every
model answer in it is replayed from a recording - but the pull request at the
end of the walk was not. Code-Fix's write tier reached the real api.github.com,
which meant a free, keyless, offline suite quietly opened a real draft pull
request on a real repository, one per run, numbered forever.

What it stands in for is the whole of that exchange: reading the source, cutting
a branch, writing a tree and a commit onto it, and proposing it. Selecting it is
one setting on each tier (`GITHUB_API_URL`), which is the point - nothing in the
read tier, the write tier or Code-Fix knows this module exists.
"""

from github_double.repository import repository
from github_double.server import app

__all__ = ["app", "repository"]
