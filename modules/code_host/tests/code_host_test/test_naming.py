"""A repository named by owner and name, out of the address it is cloned from.

That is what tells two repositories apart, and it reads no host's pages. It
assumes the name is the last two parts of the address, which holds on any host
that nests no deeper than an owner - GitHub, and a GitLab project outside a
subgroup - and is what these cases pin.
"""

from __future__ import annotations

import pytest
from argus_testkit import Scenario, the_answer_was
from code_host import owner_and_name


@pytest.mark.unit
@pytest.mark.parametrize("cloned_from", [
    "https://github.com/kuki/k8s-configs",
    "https://github.com/kuki/k8s-configs.git/",
    "git@github.com:kuki/k8s-configs.git",
    "https://gitlab.example.com/kuki/k8s-configs.git"
], ids=["https", "a url ending in .git and a slash", "ssh", "another host"])
def test_a_repository_is_named_by_the_last_two_parts_of_its_address_on_a_host_nesting_no_deeper(
    cloned_from: str
) -> None:
    Scenario() \
        .when(
            lambda: owner_and_name(cloned_from)
        ) \
        .then(
            the_answer_was("kuki/k8s-configs")
        )
