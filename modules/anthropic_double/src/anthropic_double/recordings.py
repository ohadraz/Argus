"""The on-disk store of real Anthropic responses the double replays.

One recording is one file: the raw JSON body of a real `POST /v1/messages`
response, saved verbatim. Verbatim matters - the point of the double is that
the shape it serves is a shape Anthropic actually produced, not one this repo
believes Anthropic produces. A hand-written body would drift the moment the
API grows a field, and nothing would notice.

The files live in the repo, so a fresh clone runs the integration suite with
no API key at all.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

# modules/anthropic_double/recordings/ - beside src/, not inside the package.
# These are test fixtures, not code, and they are not shipped in the wheel.
RECORDINGS_DIR = Path(__file__).resolve().parents[2] / "recordings"


class RecordingNotFound(LookupError):
    """No recording is stored under the requested name."""


def _path_for(name: str) -> Path:
    return RECORDINGS_DIR / f"{name}.json"


def available() -> list[str]:
    """Every recording name currently on disk, sorted."""
    if not RECORDINGS_DIR.exists():
        return []
    return sorted(path.stem for path in RECORDINGS_DIR.glob("*.json"))


def load(name: str) -> dict[str, Any]:
    """Returns the recorded response body stored under `name`.

    Raises `RecordingNotFound` rather than falling back to anything. A missing
    recording is a broken test setup, and a double that quietly substitutes
    some other answer would turn that into a passing test.
    """
    path = _path_for(name)
    if not path.exists():
        raise RecordingNotFound(
            f"no recording named {name!r} in {RECORDINGS_DIR} "
            f"(have: {', '.join(available()) or 'none'})"
        )
    body: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
    return body


def save(name: str, body: dict[str, Any]) -> Path:
    """Writes `body` to `name`'s file, creating the store if needed.

    Overwrites an existing recording under the same name: re-recording is how
    a stale recording gets refreshed, so refusing to overwrite would make the
    normal case the awkward one.
    """
    RECORDINGS_DIR.mkdir(parents=True, exist_ok=True)
    path = _path_for(name)
    path.write_text(json.dumps(body, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return path
