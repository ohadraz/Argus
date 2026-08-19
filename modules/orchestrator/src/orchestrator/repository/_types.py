from __future__ import annotations

from typing import Annotated

from pydantic import BeforeValidator

# psycopg returns UUID columns as `uuid.UUID` instances; Pydantic's `str`
# validation doesn't coerce those automatically
UuidStr = Annotated[str, BeforeValidator(str)]
