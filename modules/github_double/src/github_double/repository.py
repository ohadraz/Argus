"""What the double remembers: one repository, and what was proposed to it.

Kept apart from the endpoints because the two answer different questions. The
server's job is to speak GitHub's wire shapes; this one's is to be a repository
that behaves like one - a branch points at a commit, a commit points at a tree,
a tree holds files, and a proposal names a branch that exists.

Held in memory and reset between runs. Nothing here is durable on purpose: a
double that remembered yesterday's branches would answer the question "did this
run open a pull request" with the accumulated answer of every run before it,
which is precisely the failure the real API had.
"""

from __future__ import annotations

import hashlib
import io
import tarfile
from pathlib import Path
from typing import Final

from pydantic import BaseModel

# The branch a repository starts on, and the fixture it starts holding. Small
# and plausible rather than a copy of the demo app: what a replayed walk does
# with a file is decided by its recording, so the content only has to be
# readable source that the scoping setting admits.
#
# Two files are an exception, and the first is an exception to that exact
# reasoning. The large-fix scenario is about the *size* of what Code-Fix emits,
# and size is settled here rather than by any recording - a model asked to
# rewrite three lines writes three lines, whatever it was recorded doing. So
# that file is a real copy of the module the demo app's
# `monthly-statement-panel` scenario breaks in, and a byte-for-byte one: the
# shop's own log names the line the fault was raised on, and a lookalike would
# send the model to a line that says something else.
#
# The second is copied because the first one reads it. `monthly_statement.py`
# takes five fields off the `Purchase` that `accounts.py` defines, and a
# three-line stub declaring none of them is not a simplification - it is a
# contradiction, two files that cannot both be right, only one of which the
# model was asked about. Fixing the other one would be a reasonable thing to
# do and the wrong thing to have paid for.
#
# Snapshots, therefore, and ones that go stale if either module is edited
# without this being recopied. What they have to keep is the large one's size,
# the position of its fault, and the agreement between the two; they do not
# have to be the demo app's current commit.
_FIXTURE_DIR: Final = Path(__file__).parent / "fixture"
_THE_LARGE_MODULE: Final = "src/io_shop/monthly_statement.py"
_WHAT_THE_LARGE_MODULE_READS: Final = "src/io_shop/accounts.py"

DEFAULT_BASE_BRANCH: Final = "main"
DEFAULT_FILES: Final = {
    _THE_LARGE_MODULE: (_FIXTURE_DIR / "monthly_statement.py.txt").read_text(
        encoding="utf-8"
    ),
    _WHAT_THE_LARGE_MODULE_READS: (_FIXTURE_DIR / "accounts.py.txt").read_text(
        encoding="utf-8"
    ),
    "src/io_shop/spend_summary.py": (
        "def average_spend_per_item_this_month(account):\n"
        "    bought = [p for p in account.purchases if p.in_current_month]\n"
        "    return account.total_this_month_cents // len(bought)\n"
    ),
    "tests/io_shop/test_spend_summary.py": (
        "def test_the_monthly_average_is_correct_for_a_shopper_who_did_buy():\n"
        "    pass\n"
    ),
}

# How the archive names its own root. GitHub wraps a tarball in a directory
# named for the owner, the repository and the commit, and the read tier strips
# exactly one leading segment - so an archive without one loses a real segment
# of every path instead.
_ARCHIVE_ROOT: Final = "ohadraz-repository-0000000"


class Proposal(BaseModel):
    """One pull request, as the double recorded it being opened.

    Kept whole rather than counted, for the reason the Slack double keeps
    messages: what a test wants to know is not "was something proposed" but
    what a reviewer would have been shown - which branch onto which, under what
    title - and a tally could not answer it.
    """

    number: int
    title: str
    body: str
    head: str
    base: str
    draft: bool

    @property
    def html_url(self) -> str:
        """Where a reader would open it. Shaped like the real one, and pointing
        at a host that does not exist: a double that answered with a reachable
        address would put a live link in a postmortem written from a fixture."""
        return f"https://github.invalid/ohadraz/repository/pull/{self.number}"


class Repository:
    """One repository, as much of it as Argus ever touches.

    Refs, commits and trees are separate maps rather than one object graph
    because the API exposes them separately, and the write tier walks them in
    that order: a ref gives a commit, a commit gives a tree, a tree is written
    over. Collapsing them would let the double answer a step the real API would
    have refused.
    """

    def __init__(self) -> None:
        self.reset()

    def reset(self) -> None:
        """Back to one branch holding the fixture, and nothing proposed.

        Called between runs rather than at import, so a suite can say when a
        repository is fresh instead of depending on which test imported first.
        """
        self._trees: dict[str, dict[str, str]] = {}
        self._commits: dict[str, str] = {}
        self._refs: dict[str, str] = {}
        self.proposals: list[Proposal] = []

        base_tree = self.write_tree(dict(DEFAULT_FILES))
        base_commit = self.write_commit(base_tree, parents=[])
        self._refs[DEFAULT_BASE_BRANCH] = base_commit

    def write_tree(self, files: dict[str, str]) -> str:
        """Stores a tree whole and answers with the sha it was given.

        The sha is derived from the content rather than counted, so that writing
        the same tree twice is the same tree - which is what the real API does,
        and what stops a test asserting on a sha that changes with call order.
        """
        sha = _sha_of("tree", sorted(files.items()))
        self._trees[sha] = files

        return sha

    def write_commit(self, tree: str, parents: list[str]) -> str:
        """Stores a commit pointing at a tree, and answers with its sha."""
        sha = _sha_of("commit", [tree, *parents])
        self._commits[sha] = tree

        return sha

    def create_ref(self, branch: str, at: str) -> None:
        """Points a new branch at a commit.

        Refuses a branch that exists, which is the one refusal the write tier is
        written against: a re-run proposing the same incident's fix twice has to
        fail here rather than silently move somebody else's branch.
        """
        if branch in self._refs:
            raise BranchAlreadyExists(f"reference already exists: refs/heads/{branch}")

        if at not in self._commits:
            raise NoSuchObject(f"no commit [{at}] to point [{branch}] at")

        self._refs[branch] = at

    def branches(self) -> list[str]:
        """Every branch the repository has, base included.

        The base among them rather than filtered out: what a suite checks is
        what a fix wrote, and "which branches are there" is only an answer if
        the one that was always there is in it.
        """
        return sorted(self._refs)

    def head_of(self, branch: str) -> str:
        """The commit a branch points at."""
        if branch not in self._refs:
            raise NoSuchObject(f"no branch [{branch}]")

        return self._refs[branch]

    def tree_of(self, commit: str) -> str:
        """The tree a commit points at."""
        if commit not in self._commits:
            raise NoSuchObject(f"no commit [{commit}]")

        return self._commits[commit]

    def files_at(self, ref: str) -> dict[str, str]:
        """Every file readable at a ref, which may name a branch or a commit.

        Both, because the two tiers ask differently: the read tier asks for
        `main` and the write tier for the sha it just wrote. A double accepting
        only one of them would fail on whichever the caller happened to use.
        """
        commit = self._refs.get(ref, ref)

        if commit not in self._commits:
            raise NoSuchObject(f"no ref or commit [{ref}]")

        return self._trees[self._commits[commit]]

    def changed_between(self, base: str, head: str) -> list[str]:
        """Every path that differs between two refs - arrived, gone or edited.

        Content compared rather than tree shas, because a differing tree says
        only that something moved and the caller's whole question is what. Both
        sides go through `files_at`, so either may be named by a branch or by a
        commit, exactly as the real comparison accepts both.

        A path present on one side only counts as changed. The index has to be
        told about a file that went as much as about one that arrived -
        otherwise it answers for years with code the repository no longer has.
        """
        was = self.files_at(base)
        now = self.files_at(head)

        return sorted(path for path in {*was, *now} if was.get(path) != now.get(path))

    def written_over(self, base_tree: str, files: dict[str, str]) -> str:
        """A new tree: the base's files, with these written over them.

        Over rather than instead of, which is the whole reason the write tier
        reads the base tree first - a tree built from the patch alone describes
        a repository containing only the files the fix touched.
        """
        if base_tree not in self._trees:
            raise NoSuchObject(f"no tree [{base_tree}] to write over")

        return self.write_tree({**self._trees[base_tree], **files})

    def propose(self, title: str, body: str, head: str, base: str, draft: bool) -> Proposal:
        """Opens a pull request, numbered as the repository would number it.

        One counter for the whole repository, climbing and never reused - the
        real API's behaviour, and worth copying precisely because it is the
        behaviour that made a live run expensive. A double that restarted at one
        would hide a suite proposing the same fix five times.
        """
        if head not in self._refs:
            raise NoSuchObject(f"no branch [{head}] to propose from")

        proposal = Proposal(
            number=len(self.proposals) + 1,
            title=title,
            body=body,
            head=head,
            base=base,
            draft=draft
        )
        self.proposals.append(proposal)

        return proposal

    def archive_of(self, ref: str) -> bytes:
        """The repository at a ref, as the tar.gz the read tier searches.

        Built rather than stored, because it is a rendering of the tree and not
        a thing the repository holds - and wrapped in a root directory, since
        the read tier strips one segment from every path on the way in.
        """
        buffer = io.BytesIO()

        with tarfile.open(fileobj=buffer, mode="w:gz") as archive:
            for path, source in sorted(self.files_at(ref).items()):
                held = source.encode()
                member = tarfile.TarInfo(name=f"{_ARCHIVE_ROOT}/{path}")
                member.size = len(held)
                archive.addfile(member, io.BytesIO(held))

        return buffer.getvalue()


class NoSuchObject(Exception):
    """Something was asked for that this repository does not hold - answered as
    a 404, which is what the real API says and what both tiers are written to
    treat as an absence rather than a fault."""


class BranchAlreadyExists(Exception):
    """A branch was created twice - answered as a 422, the status the write
    tier's own test seeds to check that a refused branch stops a proposal."""


def _sha_of(kind: str, of: object) -> str:
    """Forty hex characters, derived from what the object is.

    Real-looking on purpose: both tiers pass these back as opaque strings, and
    a double answering `tree-1` would pass every test here and none of the
    assumptions the code makes about what a sha is.
    """
    return hashlib.sha1(f"{kind}:{of}".encode()).hexdigest()


repository = Repository()
