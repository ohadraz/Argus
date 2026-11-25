"""What a service calls, read from the organisation's own register.

The register is worth a channel of its own because of one field. What a service
calls, where, and what for are all recoverable from its source and its failures;
whether the thing on the other end belongs to the same organisation is not, and
it is what decides the response to a propagation incident. A neighbour's process
can be restarted. Another company's outage can only be named and handed over.

Nothing here infers that. A host that looks internal looks that way because
somebody chose the spelling, and the owning team does not settle it either -
somebody here owns the *integration* with a vendor. It is recorded by a person
and looked up, which is also why the register is a channel that can be wrong in
ways its reader has to survive rather than resolve.
"""

from __future__ import annotations

from typing import Protocol

from core.models import ServiceDependency


class RegistryUnavailable(Exception):
    """The register could not be asked what a service depends on.

    Deliberately not an empty list, and the consequence here is worse than the
    flag reader's. "The register was down" read as "it calls nothing" leaves the
    estate looking empty - and an estate with nothing in it is one where every
    address is outside what Argus may touch, so an outage would quietly forbid
    every mitigation instead of reporting itself.
    """


class ServiceRegister(Protocol):
    """The register, for the one question the read tier asks of it."""

    # Positional-only: the service is the whole question, and a stand-in that
    # ignores it should be free to say so in the parameter's name.
    def dependencies_of(self, service: str, /) -> list[ServiceDependency]:
        """The dependencies the register holds for `service`, in its own order.

        Empty for a service the register has no entry for, which is a real
        answer rather than a failure. Raises `RegistryUnavailable` where the
        register could not be read - and never answers an outage as empty.
        """
        ...
