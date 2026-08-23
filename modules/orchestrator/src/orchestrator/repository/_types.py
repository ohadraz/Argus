from __future__ import annotations

from argus_core.ids import UuidStr

# Re-exported so the repository's row models keep a single local import. The
# definition lives in `argus_core` because domain models need it too, and a
# domain model cannot reach into this package's private module.
__all__ = ["UuidStr"]
