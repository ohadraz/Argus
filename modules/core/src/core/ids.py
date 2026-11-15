from __future__ import annotations

from typing import Annotated
from uuid import uuid4

from pydantic import BeforeValidator

# psycopg returns UUID columns as `uuid.UUID` instances; Pydantic's `str`
# validation doesn't coerce those automatically.
UuidStr = Annotated[str, BeforeValidator(str)]


def new_id() -> str:
    """A fresh identity, generated where the object is built.

    Identity belongs to the entity, not to the table it later lands in: an
    object that is not fully itself until the database has seen it cannot be
    referenced, logged, or tested without one. Generating here also keeps
    inserts idempotent, and removes the "is this saved yet?" branch a nullable
    id forces on every reader.
    """
    return str(uuid4())
