"""The on-disk store of real Anthropic responses the double replays.

One recording is one file: the raw JSON body of a real `POST /v1/messages`
response, saved verbatim. Verbatim matters - the point of the double is that
the shape it serves is a shape Anthropic actually produced, not one this repo
believes Anthropic produces. A hand-written body would drift the moment the
API grows a field, and nothing would notice.

The files live in the repo, so a fresh clone runs the integration suite with
no API key at all.

Beside each answer, the question it answered: the request body the adapter
sent, as it was forwarded. Kept so a replay can tell an answer given to the
question now being asked from one given to a question that has since changed -
which is what lets a re-record be of the answers that went stale rather than
of every one. Kept whole rather than as a digest, because what counts as "the
same question" is a judgment about the request, and a digest would bake the
first version of that judgment into every file it was taken for.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

# modules/anthropic_double/recordings/ - beside src/, not inside the package.
# These are test fixtures, not code, and they are not shipped in the wheel.
RECORDINGS_DIR = Path(__file__).resolve().parents[2] / "recordings"

# What a stored question's file name ends in, before `.json`. A recording's
# name never ends in it, so the two cannot be mistaken for each other. Private,
# with the two functions below as the only way in: spelled again by each script
# that moves recordings, it was three spellings of one name.
_QUESTION_SUFFIX = ".request"


class RecordingNotFound(LookupError):
    """No recording is stored under the requested name."""


def _path_for(name: str) -> Path:
    return RECORDINGS_DIR / f"{name}.json"


def question_beside(answer: Path) -> Path:
    """Where the question the answer stored at `answer` was given to is
    stored: beside it, under its name with `.request` before `.json`."""
    return answer.with_name(f"{answer.stem}{_QUESTION_SUFFIX}{answer.suffix}")


def is_a_question(path: Path) -> bool:
    """Whether the file at `path` is a stored question rather than an answer."""
    return path.stem.endswith(_QUESTION_SUFFIX)


def available() -> list[str]:
    """Every recording name currently on disk, sorted - the answers, not the
    questions stored beside them."""
    if not RECORDINGS_DIR.exists():
        return []
    return sorted(path.stem for path in RECORDINGS_DIR.glob("*.json") if not is_a_question(path))


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
    return _write(_path_for(name), body)


def save_question(name: str, body: dict[str, Any]) -> Path:
    """Writes the request `name`'s answer was given to, beside it.

    Overwritten with the answer, for the same reason: a re-record replaces the
    pair, and a question left over from an earlier recording would describe an
    answer that is no longer on disk.
    """
    return _write(question_beside(_path_for(name)), body)


def load_question(name: str) -> dict[str, Any] | None:
    """The request `name`'s answer was given to - or `None` for an answer
    recorded before questions were kept, which nothing can be compared with."""
    path = question_beside(_path_for(name))
    if not path.exists():
        return None
    body: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
    return body


def _write(path: Path, body: dict[str, Any]) -> Path:
    RECORDINGS_DIR.mkdir(parents=True, exist_ok=True)
    # `newline` said explicitly, because the default translates on Windows and a
    # recording is read on three platforms. A stored answer that differs from a
    # captured one by its line endings is a diff nobody can see and every
    # reviewer has to scroll past.
    path.write_text(
        json.dumps(body, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
        newline="\n"
    )
    return path
