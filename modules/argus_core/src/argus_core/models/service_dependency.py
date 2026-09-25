"""What a service calls, as the organisation's registry records it.

A contract rather than one module's value class, and in the kernel for the
reason `PostmortemDocument` is: the read tier produces these and Mitigation
weighs them, so a type kept inside either party is one the other installs an
agent to read.

The fact that makes it worth retrieving at all is `ownership`. Everything else
here a caller could work out from its own source and its own failures - what it
calls, where, and what for - but whether the thing on the other end belongs to
the same organisation exists only in a register somebody maintains. It is also
the fact that decides what happens next: a neighbour's process can be restarted,
and another company's outage can only be named and handed over.

Nothing infers it. `pricing.io-internal.svc` looks internal because whoever named
it chose that spelling, a third party on a private link looks the same, and the
owning team does not settle it either - somebody here owns the *integration*
with a vendor. It is recorded, by a person, and looked up.
"""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel


class Ownership(StrEnum):
    """The words Argus knows for whose a dependency is.

    A vocabulary rather than a boolean, because the register is asked "whose",
    not "ours or not", and a register that has run for a year answers more than
    two ways - another division's service, a vendor a partner resells. `is_ours`
    below is what collapses that to the decision Argus makes, so the collapsing
    happens in one place instead of at every call site.

    Not the *closed* set of what a register may say, and the distinction is the
    point. This register belongs to the organisation and will grow words this
    system has never heard; what Argus owes is that an unheard-of word is never
    read as permission, which `is_ours` guarantees by testing for the one word
    that means ours rather than against the one that means somebody else's.
    """

    INTERNAL = "internal"
    THIRD_PARTY = "third-party"


class ServiceDependency(BaseModel):
    """One thing a service calls, and whose it is.

    `purpose` is carried because it is what makes the entry worth reading: a
    responder who has just learned that the failing page calls something wants
    to know what for, and a name alone sends them to the source to find out. It
    reaches the model for the same reason - an incident is diagnosed from what
    the dependency was *doing* on the request path.

    `owner` and `ownership` are both here and neither answers the other. Knowing
    a vendor's name does not say whether they can be paged; knowing they cannot
    be paged does not say who to telephone.

    `ownership` is the register's own word, kept verbatim rather than narrowed to
    the vocabulary above. Two reasons, and both are about a word Argus has never
    heard. Collapsing it on the way in loses the one thing that would explain
    the incident afterwards - that a service of the organisation's own was out of
    reach because of a single entry somebody has to go and correct. And refusing
    it on the way in would have one new word, anywhere in the register, stop
    Argus reading any of it, so every incident would escalate for a reason
    nothing in the register is wrong about.
    """

    name: str
    purpose: str
    host: str
    owner: str
    ownership: str

    @property
    def is_ours(self) -> bool:
        """Whether this is a service the organisation runs, and so one Argus
        may act on at all.

        The single question the autonomy gate asks of a dependency, answered
        here rather than by each caller comparing against a member of the enum.
        A second spelling of this comparison is a second place for a new
        ownership word to be forgotten, and being forgotten on the permissive
        side is how a restart reaches somebody else's estate.

        Tests *for* the word that means ours rather than *against* the word that
        means somebody else's, and that asymmetry is the whole safety property:
        every word this system has never heard is not-ours by construction, so a
        register that grows a fourth answer withholds authority rather than
        granting it.
        """
        return self.ownership == Ownership.INTERNAL

    @property
    def is_recognised(self) -> bool:
        """Whether the register answered in a word Argus knows at all.

        Distinct from `is_ours`, because the two failures read completely
        differently to whoever picks the incident up. A dependency that is not
        ours is a fact about the estate and the right answer is to escalate; a
        dependency nobody can classify is a fact about the *register*, and the
        right answer is to escalate and then go and fix the entry.

        Nothing gates on this. It exists so the account of the incident can say
        which of those two happened, instead of reporting an unreadable entry as
        somebody else's service.
        """
        return self.ownership in set(Ownership)
