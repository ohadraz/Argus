"""The deployment platform, as Argus needs it (spec §12.1, §13).

A port and the one adapter behind it. The port is named for the role - what
Argus asks of whatever deploys its services - and the adapter for the vendor
that answers today, in `deployment_platform.argocd`. Nothing above the port
sees a route, a selector or a response body.

The adapter is not exported here. It is built where a server is wired, and
everything else is handed it typed as a port - so the one module allowed to
name it is the one that has to.
"""

from __future__ import annotations

from deployment_platform.failures import (
    DeploymentPlatformError,
    PlatformRefused,
    PlatformUnreachable,
)
from deployment_platform.port import (
    Autoscaler,
    AutoscalerBounds,
    DeploymentPlatformReads,
    DeploymentPlatformWrites,
    DeploymentRecord,
)

__all__ = [
    "Autoscaler",
    "AutoscalerBounds",
    "DeploymentPlatformError",
    "DeploymentPlatformReads",
    "DeploymentPlatformWrites",
    "DeploymentRecord",
    "PlatformRefused",
    "PlatformUnreachable"
]
