"""A repository named by owner and name, out of the address it is cloned from.

Over HTTPS or SSH, with or without the `.git` a clone address ends in. It
assumes a repository's name is the last two parts of its address, which is true
of GitHub (`owner/name`) and of any host that nests no deeper - and is not of
one that does: a GitLab subgroup (`group/subgroup/name`) comes back as
`subgroup/name`, and an Azure DevOps address (`org/project/_git/name`) as
`_git/name`. It reads no host's pages, which is why it is the port's rather than
an adapter's; a host that nests is one an adapter would have to name.
"""

from __future__ import annotations


def owner_and_name(repo_url: str) -> str:
    """`owner/name` out of a repository's address, over HTTPS or SSH, with or
    without the `.git` a clone address ends in - its last two parts, which is
    the whole of a repository's name on a host that nests no deeper than
    an owner."""
    return "/".join(the_parts_of(repo_url)[-2:])


def the_parts_of(repo_url: str) -> list[str]:
    """The address cut at every separator, the host included: an SSH address
    puts a colon where an HTTPS one puts a slash."""
    address = repo_url.rstrip("/").removesuffix(".git").replace(":", "/")

    return [part for part in address.split("/") if part]
