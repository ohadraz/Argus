"""What GitHub answers, as the suites whose writes go to it stage it.

Shared by the two suites that write to GitHub - the branch and the retry around
every GitHub write - so each answer is spelled once.
"""

from __future__ import annotations

from typing import Final

# What GitHub answers a request to create a branch that already exists.
A_BRANCH_THAT_EXISTS_STATUS: Final = 422
