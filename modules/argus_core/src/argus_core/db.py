from __future__ import annotations

import psycopg

from argus_core.config import get_settings


def connect() -> psycopg.Connection:
    return psycopg.connect(get_settings().database_url)
