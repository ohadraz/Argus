"""Every check the judge runs on one captured case: one command, one report.

usage, from the repository root, exactly so (the allowlist matches this prefix):
  uv run python .claude/skills/judge-postmortem/scripts/judge_capture.py <capture> [<baseline>...]

<capture> is a captured test's folder - the one holding replay_log.json,
walk_double_state.json, write_up_request.json, db/, the pages and the PDF. Each
<baseline> is the same test's folder in an earlier capture, the last judged one
first: the model calls, the diverged map and the pages are set against each.

Writes only inside <capture>: every step's output under judge/, and the summary
in judge-report.md, an earlier run's report kept as judge-report-N.md. Reads the
recordings, the repository's git objects, the e2e tests (to name the recording
set) and, for links, the held stack on localhost:8000. Each step is bounded and
reported, so one that fails or stalls shows in the report instead of stopping
the rest.

The recording set's blobs are written once, to judge/recording-blobs.txt, as
judged; every later run sets the working tree and HEAD against that file, so a
run after the recording commit is the commit check.

A change before its commit is reviewed the same way, by one path:
  uv run python .claude/skills/judge-postmortem/scripts/judge_capture.py <drafts> [<earlier review>]

<drafts> is a folder laid out as the repository is (holding modules/ or tests/),
each file in it a drafted whole file; the repository's root drafts nothing. The
working tree's diff against HEAD and each draft's diff against the repository's
own file go into a new folder under .claude/local/reviews/, summed up in its
review.md, with a copy of every draft and every untracked Python file and the
HEAD it was taken on. With <earlier review> (a folder under reviews/), each
draft - and each file whose working-tree diff moved - is also set against the
text that review saw, in since.diff: its copy where it kept one, else HEAD's
text with that review's two diffs laid on, so a second look reads only what is
new since the first.

On resume, what came after the handover was written is read back by the same path
(resume.py, beside this script, says what it writes):
  uv run python .claude/skills/judge-postmortem/scripts/judge_capture.py resume <jsonl> [<since>]
"""

import difflib
import json
import os
import re
import shutil
import subprocess
import sys
import time
import traceback
from collections.abc import Callable
from pathlib import Path
from typing import Any

sys.dont_write_bytecode = True

SCRIPTS = Path(__file__).resolve().parent
REPO = SCRIPTS.parents[3]
RECORDINGS = REPO / "modules" / "anthropic_double" / "recordings"
E2E = REPO / "tests" / "e2e"
REVIEWS = REPO / ".claude" / "local" / "reviews"
CODE = ("modules/", "tests/", "scripts/")
PYTHON = sys.executable
UNREACHABLE = "http://127.0.0.1:9"
MODES = ("both", "grep", "meaning")
INTENT_TOOLS = {"submit_meaning"}
GROUNDING_JUDGE_TOOLS = {"flag_ungrounded_claims", "judge_claims"}
WRITE_UP_TOOLS = {"submit_postmortem", "order_chain"}
PRICES = {"opus": (4, 5, 0.20, 20), "sonnet": (2, 2.50, 0.20, 10)}
PAGES = ("postmortem_page", "postmortem_pdf", "walk_page", "incident_page", "synopsis_pdf",
         "slack")

# The double's own masks (anthropic_double.server): what a run writes differently
# every time, so what is left is wording and which lines a request holds.
RUN_SPECIFIC = re.compile(
    r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}"
    r"|\b[0-9a-f]{7,40}\b"
    r"|\d+"
)
A_SPAN = re.compile(
    r"\b\d+ (?:day|hour|minute|second)s?(?: \d+ (?:day|hour|minute|second)s?)*\b"
    r"|\bless than a second\b"
)
A_DAY = re.compile(r"\b(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec) \d{1,2}\b")
FIGURES_ONLY = re.compile(r"^[-.,:TZ #]*#[-#.,:TZ ]*$")

# judge_case.py's page masks: ids, then any run of digits with its separators.
UUID = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}")
DIGITS = re.compile(r"\d[\d,.:]*")

CONSTANT = re.compile(r'^(RECORDED_[A-Z0-9_]+)\s*(?::[^=]+)?=\s*"([^"]+)"', re.MULTILINE)
RECORDED = re.compile(r"\bRECORDED_[A-Z0-9_]+\b")
TOP_LEVEL = re.compile(r"^(?:@|async def|def|class|[A-Za-z_][A-Za-z0-9_]*\s*(?::[^=\n]+)?=)",
                       re.MULTILINE)
NAME = re.compile(r"^([A-Za-z_][A-Za-z0-9_]*)", re.MULTILINE)
LEAK = re.compile(r"\{[A-Z]{1,3}[0-9a-f]*\.\d+[^}]*\}"
                  r"|\bNone\b|\bnan\b|\bnull\b|undefined|Traceback")
ACTION_WORDS = re.compile(
    r"\b(turning|turned|reverting|reverted|revert|rolling|rolled|restor\w*|brought|"
    r"put back|confirmed|refuted|recover\w*|mitigat\w*|undo\w*|undone)\b", re.IGNORECASE)


class Judge:
    """One capture's run: its output folder, the report's sections, and what
    the steps share - the recording set's answers."""

    def __init__(self, capture: Path, baselines: list[Path]) -> None:
        self.capture = capture
        self.baselines = baselines
        self.out = capture / "judge"
        self.out.mkdir(parents=True, exist_ok=True)
        self.sections: list[str] = []
        self.answers: list[Path] = []

    def step(self, name: str, work: Callable[[], list[str]]) -> None:
        started = time.monotonic()
        try:
            lines, status = work(), "ok"
        except Exception:  # noqa: BLE001 - a failing step is reported, the rest still run
            lines, status = traceback.format_exc().splitlines(), "FAILED"
        took = time.monotonic() - started
        print(f"{name:18} {status:7} {took:6.1f}s", flush=True)
        self.sections.append(f"## {name} - {status} ({took:.1f}s)\n\n```\n"
                             + "\n".join(lines) + "\n```\n")

    def write(self, relative: str, text: str) -> Path:
        path = self.out / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
        return path

    def label(self, baseline: Path) -> str:
        return baseline.parent.name or baseline.name


def run(args: list[str], cwd: Path, timeout: int) -> tuple[str, str]:
    """A helper script or git, bounded; its exit and everything it printed."""
    environment = dict(os.environ, PYTHONDONTWRITEBYTECODE="1")
    try:
        done = subprocess.run(args, capture_output=True, text=True, encoding="utf-8",
                              errors="replace", timeout=timeout, cwd=cwd, env=environment)
        return f"exit {done.returncode}", done.stdout + done.stderr
    except subprocess.TimeoutExpired as expired:
        printed = expired.stdout if isinstance(expired.stdout, str) else ""
        return f"TIMED OUT after {timeout}s", printed or ""


def script(judge: Judge, name: str, *args: str, timeout: int = 300) -> tuple[str, str]:
    return run([PYTHON, "-B", "-X", "utf8", str(SCRIPTS / name), *args], judge.out, timeout)


def git(*args: str) -> str:
    _, printed = run(["git", "--no-optional-locks", "-C", str(REPO), *args], REPO, 60)
    return printed.strip()


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


# ---- the model calls ------------------------------------------------------


def turn_text(turn: dict[str, Any]) -> list[str]:
    lines = []
    if "results" in turn:
        for result in turn["results"]:
            failed = " FAILED" if result.get("failed") else ""
            lines.append(f"[RESULT {result.get('call_id')}{failed}]")
            lines.append(str(result.get("content")))
        rest = {k: v for k, v in turn.items() if k != "results"}
        if rest:
            lines.append(f"[ALSO] {json.dumps(rest, ensure_ascii=False)}")
        return lines
    if turn.get("reasoning"):
        lines.append("[REASONING]\n" + turn["reasoning"])
    if turn.get("text"):
        lines.append(turn["text"])
    for call in turn.get("tool_calls") or []:
        lines.append(f"[CALL {call.get('name')} {call.get('id')}]")
        lines.append(json.dumps(call.get("arguments"), indent=1, ensure_ascii=False))
    other = {k: v for k, v in turn.items()
             if k not in ("text", "reasoning", "tool_calls", "input_tokens", "output_tokens",
                          "cache_read_tokens", "cache_write_tokens")}
    if other:
        lines.append(f"[ALSO] {json.dumps(other, ensure_ascii=False)}")
    return lines


def llm_calls(capture: Path) -> list[tuple[int, str, dict[str, Any], dict[str, Any]]]:
    rows = read_json(capture / "replay_log.json")
    return [(int(seq), target, request, response or {})
            for seq, kind, target, request, response in rows if kind == "llm"]


def tool_names(request: dict[str, Any]) -> list[str]:
    return [tool.get("name") for tool in request.get("tools", [])]


def render_calls(capture: Path, folder: Path) -> list[str]:
    folder.mkdir(parents=True, exist_ok=True)
    said = []
    for seq, target, request, response in llm_calls(capture):
        lines = [f"===== seq {seq} {target} max_tokens {request.get('max_tokens')}"]
        for tool in request.get("tools", []):
            lines.append(f"[TOOL {tool.get('name')}] required {tool.get('required')}")
            lines.append(str(tool.get("description")))
            lines.append(json.dumps(tool.get("properties"), indent=1, ensure_ascii=False))
        for index, turn in enumerate(request.get("transcript", [])):
            lines.append(f"----- turn {index}")
            lines.extend(turn_text(turn))
        lines.append("===== ANSWER")
        lines.extend(turn_text(response))
        name = f"{seq:02d}-{target}.txt"
        (folder / name).write_text("\n".join(lines), encoding="utf-8")
        turns = len(request.get("transcript", []))
        said.append(f"{name}: {turns} turns, tools {tool_names(request)}")
    return said


def masked_lines(text: str) -> list[str]:
    out: list[str] = []
    for line in text.splitlines():
        line = RUN_SPECIFIC.sub("#", A_SPAN.sub("#", A_DAY.sub("#", line)))
        if FIGURES_ONLY.match(line):
            if out and out[-1] == "<rows>":
                continue
            line = "<rows>"
        out.append(line)
    return out


def changed(diff: list[str]) -> int:
    return sum(1 for d in diff if d[:1] in "+-" and d[:3] not in ("+++", "---"))


def step_calls(judge: Judge) -> list[str]:
    return render_calls(judge.capture, judge.out / "calls")


def calls_by_what_they_were(capture: Path) -> dict[tuple[str, tuple[str, ...], int], str]:
    """Each model call's rendered file name, keyed by the model, its tools and which time
    that pair was called - so a call added mid-walk (the grounding judge's) shifts no
    pairing, where pairing by sequence number compares an overview with an ordering."""
    seen: dict[tuple[str, tuple[str, ...]], int] = {}
    keyed = {}
    for seq, target, request, _ in llm_calls(capture):
        kind = (target, tuple(tool_names(request)))
        seen[kind] = seen.get(kind, 0) + 1
        keyed[(*kind, seen[kind])] = f"{seq:02d}-{target}.txt"
    return keyed


def step_calls_against_baselines(judge: Judge) -> list[str]:
    said = []
    ours = calls_by_what_they_were(judge.capture)
    for baseline in judge.baselines:
        label = judge.label(baseline)
        theirs = judge.out / "baselines" / label / "calls"
        render_calls(baseline, theirs)
        their_calls = calls_by_what_they_were(baseline)
        said.append(f"== against {label} (paired by model, tools and turn; ids, digits, spans and"
                    " days masked as the double does)")
        for key, name in ours.items():
            tools = ", ".join(key[1])
            their_name = their_calls.get(key)
            if their_name is None:
                said.append(f"NEW   {name}  [{tools}]")
                continue
            path = judge.out / "calls" / name
            before = theirs / their_name
            diff = list(difflib.unified_diff(
                masked_lines(before.read_text(encoding="utf-8")),
                masked_lines(path.read_text(encoding="utf-8")),
                f"{label}/{their_name}", f"capture/{name}", n=2, lineterm=""))
            judge.write(f"baselines/{label}/calls-diff/{name}", "\n".join(diff))
            verdict = "DIFF " if diff else "SAME "
            said.append(f"{verdict} {name} (theirs {their_name})  {changed(diff)} changed lines"
                        f"  [{tools}]")
        for key, their_name in their_calls.items():
            if key not in ours:
                said.append(f"GONE  {their_name}  [{', '.join(key[1])}]")
    return said or ["no baseline given"]


def step_answers(judge: Judge) -> list[str]:
    """Every tool call each model answered with, whole - the Investigator's weighing and
    answer, Code-Fix's submit and its answer to the question, the write-up's submits."""
    lines = []
    for seq, target, _, response in llm_calls(judge.capture):
        for call in response.get("tool_calls") or []:
            lines.append(f"== seq {seq} {target}: {call.get('name')}")
            lines.append(json.dumps(call.get("arguments"), indent=1, ensure_ascii=False))
    judge.write("answers.txt", "\n".join(lines))
    names = [line for line in lines if line.startswith("== ")]
    return [*names, "(whole calls in judge/answers.txt)"]


# ---- the recording set ----------------------------------------------------


def blocks_of(text: str) -> list[tuple[str, str]]:
    starts = [found.start() for found in TOP_LEVEL.finditer(text)]
    blocks, pending = [], ""
    for index, start in enumerate(starts):
        end = starts[index + 1] if index + 1 < len(starts) else len(text)
        head = text[start:end]
        if head.startswith("@"):
            pending += head
            continue
        named = re.match(r"(?:async def|def|class)\s+([A-Za-z_][A-Za-z0-9_]*)", head) \
            or NAME.match(head)
        blocks.append((named.group(1) if named else "?", pending + head))
        pending = ""
    return blocks


def constants_reached(body: str, module_names: dict[str, str], seen: set[str]) -> set[str]:
    reached = set(RECORDED.findall(body))
    for name, text in module_names.items():
        if name in seen or not re.search(rf"\b{re.escape(name)}\b", body):
            continue
        seen.add(name)
        reached |= constants_reached(text, module_names, seen)
    return reached


def recordings_named_by(test: str) -> list[str]:
    framework = (E2E / "framework" / "argus.py").read_text(encoding="utf-8")
    name_of = dict(CONSTANT.findall(framework))
    for path in sorted(E2E.glob("test_*.py")):
        blocks = blocks_of(path.read_text(encoding="utf-8"))
        module_names = {name: body for name, body in blocks if not name.startswith("test_")}
        for name, body in blocks:
            if name == test:
                reached = constants_reached(body, module_names, {name})
                return sorted(name_of[c] for c in reached if c in name_of)
    return []


def numbered(path: Path) -> int:
    found = re.search(r"-(\d+)(?:\.request)?\.json$", path.name)
    return int(found.group(1)) if found else 1


def modes_of(name: str, diverged: dict[str, str]) -> list[str]:
    """The mode the run replayed - the diverged map names it where anything diverged;
    otherwise the first mode the set is recorded in."""
    named = [mode for mode in MODES if any(key.startswith(f"{mode}-{name}") for key in diverged)]
    recorded = [mode for mode in MODES if (RECORDINGS / f"{mode}-{name}.json").exists()]
    return named or recorded[:1]


def step_recording_set(judge: Judge) -> list[str]:
    diverged = state_of(judge.capture).get("diverged") or {}
    names = recordings_named_by(judge.capture.name)
    lines = [f"test {judge.capture.name} replays: {names or 'nothing found in tests/e2e'}"]
    for name in names:
        for mode in modes_of(name, diverged):
            exact = re.compile(rf"{re.escape(mode)}-{re.escape(name)}(?:-\d+)?\.json")
            candidates = RECORDINGS.glob(f"{mode}-{name}*.json")
            found = sorted((p for p in candidates if exact.fullmatch(p.name)), key=numbered)
            judge.answers.extend(found)
            lines.append(f"{mode}-{name}: {len(found)} answers")
    return lines


def request_of(answer: Path) -> Path:
    return answer.with_name(answer.stem + ".request.json")


def judge_recordings(judge: Judge) -> list[Path]:
    """The grounding judge's answers on the set's write-ups, named after the set:
    committed with it, so hashed and priced with it."""
    found: list[Path] = []
    for stem in sorted({re.sub(r"-\d+$", "", answer.stem) for answer in judge.answers}):
        exact = re.compile(rf"judge-{re.escape(stem)}(?:-\d+)?\.json")
        found += sorted((path for path in RECORDINGS.glob(f"judge-{stem}*.json")
                         if exact.fullmatch(path.name)), key=numbered)
    return found


def set_files(judge: Judge) -> list[Path]:
    files = []
    for answer in [*judge.answers, *judge_recordings(judge)]:
        files.append(answer)
        if request_of(answer).exists():
            files.append(request_of(answer))
    stems = {re.sub(r"-\d+$", "", answer.stem) for answer in judge.answers}
    anchors = [RECORDINGS / f"{stem}.anchor" for stem in sorted(stems)]
    files.extend(anchor for anchor in anchors if anchor.exists())
    return sorted(files, key=lambda path: path.name)


def tools_of(answer: Path) -> set[str]:
    if not request_of(answer).exists():
        return set()
    return set(tool_names(read_json(request_of(answer))))


def write_up_answers(judge: Judge) -> list[Path]:
    return [answer for answer in judge.answers if tools_of(answer) & WRITE_UP_TOOLS]


def step_cost(judge: Judge) -> list[str]:
    lines, total = [], 0.0
    judged_by = judge_recordings(judge)
    for answer in [*judge.answers, *judged_by]:
        request = request_of(answer)
        model = read_json(request).get("model", "") if request.exists() else "?"
        body = read_json(answer)
        usage = body.get("usage") or body.get("response", {}).get("usage", {})
        i, w, r, o = PRICES["sonnet" if "sonnet" in model else "opus"]
        each = (usage.get("input_tokens", 0) * i
                + usage.get("cache_creation_input_tokens", 0) * w
                + usage.get("cache_read_input_tokens", 0) * r
                + usage.get("output_tokens", 0) * o) / 1e6
        total += each
        lines.append(f"{answer.name:60} {model:22} {each:.4f}")
    lines.append(f"total {total:.4f} over {len(judge.answers)} answers and "
                 f"{len(judged_by)} grounding-judge calls")
    return lines


def step_exchange(judge: Judge) -> list[str]:
    answers = [str(answer) for answer in write_up_answers(judge)]
    if not answers:
        return ["no write-up recordings in the set"]
    status, printed = script(judge, "recording_exchange.py", str(judge.out / "exchange"), *answers)
    return [f"recording_exchange.py {status}", *printed.splitlines()]


def step_fields(judge: Judge) -> list[str]:
    answers = [str(answer) for answer in write_up_answers(judge)]
    if not answers:
        return ["no write-up recordings in the set"]
    status, printed = script(judge, "fields.py", *answers)
    judge.write("fields.txt", printed)
    return [f"fields.py {status}", *printed.splitlines()]


def blobs_in(text: str) -> dict[str, str]:
    pairs = (line.split(" ", 1) for line in text.splitlines() if line)
    return {name: blob for blob, name in pairs}


def step_blobs(judge: Judge) -> list[str]:
    files = set_files(judge)
    now = [f"{git('hash-object', path.relative_to(REPO).as_posix())} {path.name}" for path in files]
    judge.write("recording-blobs-now.txt", "\n".join(now) + "\n")
    judged_file = judge.out / "recording-blobs.txt"
    lines = []
    if not judged_file.exists():
        judged_file.write_text("\n".join(now) + "\n", encoding="utf-8")
        lines.append(f"{len(now)} files hashed as judged into judge/recording-blobs.txt")
    judged = blobs_in(judged_file.read_text(encoding="utf-8"))
    gained = [line for line in now if line.split(" ", 1)[1] not in judged]
    if gained:
        with judged_file.open("a", encoding="utf-8") as kept:
            kept.write("\n".join(gained) + "\n")
        lines.append(f"{len(gained)} files the set gained, hashed NOW rather than when judged: "
                     f"{[line.split(' ', 1)[1] for line in gained]}")
        judged = blobs_in(judged_file.read_text(encoding="utf-8"))
    tree = blobs_in("\n".join(now))
    differ = [name for name in judged if tree.get(name) != judged[name]]
    lines.append(f"working tree: {len(judged) - len(differ)} of {len(judged)} as judged"
                 + (f"; differ: {differ}" if differ else ""))
    sha, parents, subject = ([*git("log", "-1", "--format=%H%n%P%n%s").splitlines(), "", ""])[:3]
    held = [name for name in judged
            if git("rev-parse", f"HEAD:{RECORDINGS.relative_to(REPO).as_posix()}/{name}")
            == judged[name]]
    lines.append(f"HEAD {sha} (parents {parents}): {len(held)} of {len(judged)} blobs as judged")
    lines.append(f"HEAD's line: {subject}")
    paths = git("diff-tree", "--no-commit-id", "--name-status", "-r", "HEAD").splitlines()
    outside = [path for path in paths if not any(path.endswith(name) for name in judged)]
    lines.append(f"HEAD changes {len(paths)} paths; outside the set: {outside or 'none'}")
    return lines


def judged_head(judge: Judge) -> str:
    """The HEAD the capture was judged on, kept the first time it is asked - or,
    for a capture judged before it was kept, the HEAD its last report names."""
    kept = judge.out / "judged-head.txt"
    if not kept.exists():
        report = judge.capture / "judge-report.md"
        named = (re.search(r"^HEAD ([0-9a-f]{40}) ", report.read_text(encoding="utf-8"), re.M)
                 if report.exists() else None)
        kept.write_text((named.group(1) if named else git("rev-parse", "HEAD")) + "\n",
                        encoding="utf-8")
    return kept.read_text(encoding="utf-8").strip()


def step_commits(judge: Judge) -> list[str]:
    """Every commit since the capture was judged: its files, whether each holds
    what the working tree does, and its diff outside the recordings
    (judge/commits/), to read against the diffs that were reviewed."""
    since = judged_head(judge)
    recordings = RECORDINGS.relative_to(REPO).as_posix()
    shas = git("log", "--reverse", "--format=%H", f"{since}..HEAD").splitlines()
    lines = [f"judged on {since[:8]}; {len(shas)} commit(s) since"]
    for sha in shas:
        lines.append(f"{sha[:8]} {git('log', '-1', '--format=%s', sha)}")
        changed = git("diff-tree", "--no-commit-id", "--name-only", "-r", sha).splitlines()
        differ = [path for path in changed
                  if (REPO / path).exists()
                  and git("rev-parse", f"{sha}:{path}") != git("hash-object", path)]
        code = [path for path in changed if not path.startswith(recordings)]
        judge.write(f"commits/{sha[:8]}.diff",
                    git("show", "--format=", sha, "--", *code) if code else "")
        lines.append(f"  {len(changed)} files, {len(code)} outside the recordings; "
                     f"differing from the working tree: {differ or 'none'}")
        lines.extend(f"    {path}" for path in code)
    return lines


# ---- the double, the pages, Slack and the record ---------------------------


def state_of(capture: Path) -> dict[str, Any]:
    state = capture / "walk_double_state.json"
    return read_json(state) if state.exists() else {}


def step_diverged(judge: Judge) -> list[str]:
    lines = [f"capture: {state_of(judge.capture).get('diverged')}"]
    for baseline in judge.baselines:
        lines.append(f"{judge.label(baseline)}: {state_of(baseline).get('diverged')}")
    return lines


def texts_of_messages(recorded: dict[str, Any]) -> list[str]:
    texts = []
    for message in recorded["messages"]:
        content = message["content"]
        blocks = content if isinstance(content, list) else [{"text": content}]
        for block in blocks:
            texts.append(block.get("text") or block.get("thinking")
                         or json.dumps(block.get("input") or block.get("content")))
    return texts


def strings_of(value: Any) -> list[str]:
    if isinstance(value, str):
        return [value]
    if isinstance(value, dict):
        return [s for key in value for s in strings_of(value[key])]
    if isinstance(value, list):
        return [s for item in value for s in strings_of(item)]
    return []


def step_recorded_against_asked(judge: Judge) -> list[str]:
    """Each diverged recording's own question set against the one this run asked, paired
    with the walk's calls in order: the intent double's and the grounding judge's calls
    are not the walk's, and counting one shifts every pair after it."""
    walk = [(seq, request) for seq, _, request, _ in llm_calls(judge.capture)
            if not set(tool_names(request)) & (INTENT_TOOLS | GROUNDING_JUDGE_TOOLS)]
    diverged = state_of(judge.capture).get("diverged") or {}
    lines = [f"{len(walk)} walk calls, {len(judge.answers)} answers in the set"]
    for (seq, request), answer in zip(walk, judge.answers, strict=False):
        if answer.stem not in diverged or not request_of(answer).exists():
            continue
        recorded = read_json(request_of(answer))
        diff = list(difflib.unified_diff(
            masked_lines("\n".join(texts_of_messages(recorded))),
            masked_lines("\n".join(strings_of(request.get("transcript")))),
            "recorded", "asked", n=2, lineterm=""))
        judge.write(f"diverged/{answer.stem}.diff", "\n".join(diff))
        lines.append(f"{answer.stem} ({diverged[answer.stem]}) against seq {seq}: "
                     f"{changed(diff)} changed lines - judge/diverged/{answer.stem}.diff")
        lines.extend("  " + line[:200] for line in diff
                     if line[:1] in "+-" and line[:3] not in ("+++", "---"))
    return lines


def step_pages(judge: Judge) -> list[str]:
    lines = []
    for name in ("check_pages.py", "check_pdf.py"):
        status, printed = script(judge, name, str(judge.capture), str(judge.out / "text"))
        lines += [f"{name} {status}", *printed.splitlines()]
    write_slack_text(judge.capture, judge.out / "text")
    return lines


def slack_lines(capture: Path) -> list[str]:
    """The Slack posts from the last opening, each as where it went and its words."""
    posted = read_json(capture / "slack_posted.json")["posted"]
    starts = [i for i, message in enumerate(posted)
              if message["text"].startswith("Argus: Received")]
    return [f"{'thread ' if message.get('thread_ts') else 'CHANNEL'}"
            f"{' (updated)' if message.get('updated') else ''} {message['text']}"
            for message in (posted[starts[-1]:] if starts else posted)]


def write_slack_text(capture: Path, folder: Path) -> None:
    """Slack's posts as text beside the pages', for the diff against a baseline -
    the overview's words and the postmortem's summary reach Slack whole."""
    if (capture / "slack_posted.json").exists():
        folder.mkdir(parents=True, exist_ok=True)
        (folder / "slack.txt").write_text("\n".join(slack_lines(capture)), encoding="utf-8")


def masked_page(text: str) -> list[str]:
    return [DIGITS.sub("#", UUID.sub("<id>", line)) for line in text.splitlines()]


def step_pages_against_baselines(judge: Judge) -> list[str]:
    lines = []
    for baseline in judge.baselines:
        label = judge.label(baseline)
        theirs = judge.out / "baselines" / label / "text"
        script(judge, "check_pages.py", str(baseline), str(theirs), UNREACHABLE)
        script(judge, "check_pdf.py", str(baseline), str(theirs))
        write_slack_text(baseline, theirs)
        lines.append(f"== against {label} (ids and digits masked)")
        for name in PAGES:
            mine, before = judge.out / "text" / f"{name}.txt", theirs / f"{name}.txt"
            if not mine.exists() or not before.exists():
                lines.append(f"{name}: not on both sides")
                continue
            diff = list(difflib.unified_diff(masked_page(before.read_text(encoding="utf-8")),
                                             masked_page(mine.read_text(encoding="utf-8")),
                                             label, "capture", n=0, lineterm=""))
            written = f"baselines/{label}/pages-diff/{name}.diff"
            judge.write(written, "\n".join(diff))
            lines.append(f"{name}: {changed(diff)} changed lines - judge/{written}")
    return lines or ["no baseline given"]


def step_slack(judge: Judge) -> list[str]:
    posted = read_json(judge.capture / "slack_posted.json")["posted"]
    starts = [i for i, message in enumerate(posted)
              if message["text"].startswith("Argus: Received")]
    mine = posted[starts[-1]:] if starts else posted
    lines = [f"{len(posted)} posted in all, {len(mine)} from the last opening"]
    for number, message in enumerate(mine, 1):
        where = "thread " if message.get("thread_ts") else "CHANNEL"
        updated = " (updated)" if message.get("updated") else ""
        lines.append(f"{number:2} {where}{updated} {message['text']}")
    judge.write("slack.txt", "\n".join(lines))
    return lines


def rows_of(capture: Path, table: str) -> list[dict[str, Any]]:
    path = capture / "db" / f"{table}.json"
    if not path.exists():
        return []
    rows = read_json(path)
    return rows if isinstance(rows, list) else [rows]


def row_text(row: dict[str, Any], width: int) -> str:
    return json.dumps({key: str(value)[:width] for key, value in row.items()}, ensure_ascii=False)


def said_of(payload: Any) -> str:
    """A status move's words - its `detail` - from the payload as dumped: a
    mapping, or the JSON text of one. Read by key, not by pattern: a detail
    holding an apostrophe ("the alarm's own claim") is quoted otherwise."""
    if isinstance(payload, str):
        try:
            payload = json.loads(payload)
        except ValueError:
            return ""
    return str(payload.get("detail") or "") if isinstance(payload, dict) else ""


def step_record(judge: Judge) -> list[str]:
    lines = []
    for incident in rows_of(judge.capture, "incident"):
        lines.append(f"incident {incident.get('id')} {incident.get('status')}: "
                     f"created_at {incident.get('created_at')}, "
                     f"ended_at {incident.get('ended_at')}")
    events = rows_of(judge.capture, "incident_event")
    lines.append(f"{len(events)} events: " + ", ".join(str(row.get("kind")) for row in events))
    for row in events:
        if row.get("kind") == "status-changed":
            lines.append(f"  status-changed at {row.get('at')}: {said_of(row.get('payload'))}")
    for row in rows_of(judge.capture, "incident_reference"):
        lines.append(f"reference {row.get('source')} {row.get('kind')} {row.get('value')} "
                     f"recorded_at {row.get('recorded_at')}")
    for row in rows_of(judge.capture, "thread_message"):
        lines.append(f"message by {row.get('person_name')} written_at {row.get('written_at')} "
                     f"meaning {row.get('meaning')} standing {row.get('standing')}: "
                     f"{row.get('text')}")
        if row.get("standing_reason"):
            lines.append(f"  standing reason: {row.get('standing_reason')}")
    lines.extend("action " + row_text(row, 120) for row in rows_of(judge.capture, "action"))
    lines.extend("hypothesis " + row_text(row, 160)
                 for row in rows_of(judge.capture, "hypothesis"))
    return lines


def step_pdf_against_page(judge: Judge) -> list[str]:
    if not (judge.out / "text" / "postmortem_pdf.txt").exists():
        return ["no postmortem PDF read: the incident wrote no postmortem"]
    page = (judge.out / "text" / "postmortem_page.txt").read_text(encoding="utf-8")
    pdf = (judge.out / "text" / "postmortem_pdf.txt").read_text(encoding="utf-8")
    pdf = re.sub(r"Argus postmortem · written[^\n]*\n", "", pdf)
    flat = re.sub(r"\s+", " ", pdf.replace("­", ""))
    missing = []
    for line in page.splitlines():
        if "|" in line:
            continue
        for sentence in re.split(r"(?<=[.!?])\s+", line):
            said = re.sub(r"\s+", " ", sentence).strip()
            if len(said) > 40 and said not in flat:
                missing.append(said)
    return [f"{len(missing)} prose sentences of the page not found whole in the PDF "
            "(table rows left out; a hit may be a line the PDF wraps or joins)",
            *("- " + said[:220] for said in missing)]


def step_leaks(judge: Judge) -> list[str]:
    lines = []
    for path in sorted((judge.out / "text").glob("*.txt")):
        for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            if LEAK.search(line):
                lines.append(f"{path.name}:{number}: {line[:200]}")
    return lines or ["no unresolved placeholder, None, nan, null, undefined or Traceback"]


def change_steps_of(path: Path) -> list[str]:
    try:
        body = read_json(path)
    except (json.JSONDecodeError, UnicodeDecodeError):
        return []
    content = body.get("content") or body.get("response", {}).get("content") or []
    steps = []
    for block in content:
        if (isinstance(block, dict) and block.get("type") == "tool_use"
                and block.get("name") == "submit_postmortem"):
            chain = (block.get("input") or {}).get("causal_chain") or []
            steps.extend(step.get("step") or "" for step in chain if step.get("ruled_out"))
    return steps


def step_change_steps(judge: Judge) -> list[str]:
    """The change step - the causal-chain step carrying ruled_out - of every recorded
    write-up, so a point about it can be set against the closed cases at once."""
    mine = {answer.name for answer in judge.answers}
    lines, marked = [], 0
    for path in sorted(RECORDINGS.glob("*.json")):
        if path.name.endswith(".request.json"):
            continue
        for said in change_steps_of(path):
            hit = ACTION_WORDS.search(said)
            marked += bool(hit)
            whose = "THIS " if path.name in mine else "     "
            lines.append(f"{whose}{'HIT ' if hit else '    '}{path.stem}: {said}")
    judge.write("change-steps.txt", "\n".join(lines))
    return [f"{len(lines)} change steps in the recordings, {marked} naming an action or verdict "
            "(judge/change-steps.txt); this set's:",
            *(line for line in lines if line.startswith("THIS"))]


def step_lint(judge: Judge) -> list[str]:
    """The judge's own scripts as `nox -s lint` sees them, since they sit in the repo; no
    cache, so nothing is written outside the capture."""
    status, printed = run([PYTHON, "-m", "ruff", "check", "--no-cache", "--output-format",
                           "concise", str(SCRIPTS)], REPO, 120)
    return [f"ruff {status}", *printed.splitlines()]


def helper(judge: Judge, name: str, *args: str, keep: str | None = None) -> Callable[[], list[str]]:
    def work() -> list[str]:
        status, printed = script(judge, name, *args)
        if keep:
            judge.write(keep, printed)
        return [f"{name} {status}", *printed.splitlines()]
    return work


HUNK = re.compile(r"^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@")
DRAFT_LINE = re.compile(r"^\s*(?:\d+|NEW)\s+(\S+)$")


def diff_sections(text: str) -> dict[str, list[str]]:
    """Each file's part of a unified diff, keyed by the path its +++ line names,
    unquoted and with forward slashes, so a no-index diff's absolute path can be
    found by its ending."""
    sections: dict[str, list[str]] = {}
    block: list[str] = []
    for line in text.splitlines():
        if line.startswith("diff --git "):
            block = []
        block.append(line)
        if line.startswith("+++ "):
            named = line[4:].strip().strip('"').replace("\\\\", "/").replace("\\", "/")
            sections[named] = block
    return sections


def section_for(sections: dict[str, list[str]], relative: str) -> list[str] | None:
    return next((block for named, block in sections.items()
                 if named.endswith(f"/{relative}")), None)


def changed_lines(diff: str) -> int:
    return sum(1 for line in diff.splitlines()
               if line[:1] in ("+", "-") and not line.startswith(("+++", "---")))


def patched(text: str, block: list[str]) -> str:
    """text with one file's diff laid on, each hunk where its header puts it and
    its old lines matched exactly: a mismatch raises, since it means text is not
    what the diff was taken from."""
    if any(line.startswith("\\ No newline") for line in block):
        raise ValueError("a side without a final newline is not handled")
    source = text.split("\n")
    if source[-1] == "":
        source.pop()
    out: list[str] = []
    at, index = 0, 0
    while index < len(block):
        header = HUNK.match(block[index])
        index += 1
        if not header:
            continue
        start, count = int(header[1]), int(header[2] or 1)
        left_old, left_new = count, int(header[4] or 1)
        old: list[str] = []
        new: list[str] = []
        while left_old > 0 or left_new > 0:
            line = block[index] or " "
            index += 1
            tag, body = line[0], line[1:]
            if tag not in " -+":
                raise ValueError(f"not a hunk line: {line!r}")
            if tag in " -":
                old.append(body)
                left_old -= 1
            if tag in " +":
                new.append(body)
                left_new -= 1
        first = start - 1 if count else start
        if source[first:first + len(old)] != old:
            raise ValueError(f"the hunk at line {start} does not match")
        out += source[at:first] + new
        at = first + len(old)
    return "\n".join(out + source[at:]) + "\n"


def earlier_text(relative: str, earlier: Path) -> tuple[str | None, str]:
    """A file as an earlier review saw it, and how that was got: the review's copy
    of the draft, else the file at the review's HEAD (or the review's copy of it
    untracked) with the review's working-tree diff and draft diff laid on."""
    kept = earlier / "drafts" / relative
    if kept.exists():
        return kept.read_text(encoding="utf-8"), "the review's copy"
    head_file = earlier / "head.txt"
    head = head_file.read_text(encoding="utf-8").strip() if head_file.exists() else "HEAD"
    status, text = run(["git", "--no-optional-locks", "-C", str(REPO), "show",
                        f"{head}:{relative}"], REPO, 60)
    how = head[:8]
    if status != "exit 0":
        kept = earlier / "untracked" / relative
        if not kept.exists():
            return None, "untracked then and not kept - read it whole"
        text, how = kept.read_text(encoding="utf-8"), "the review's untracked copy"
    for name, label in (("worktree.diff", "working tree"), ("drafts.diff", "draft")):
        diff = earlier / name
        block = (section_for(diff_sections(diff.read_text(encoding="utf-8")), relative)
                 if diff.exists() else None)
        if block:
            text = patched(text, block)
            how += f" + {label}"
    return text, how


def since_section(drafts: Path, drafted: list[Path], earlier: Path, out: Path) -> list[str]:
    """Every file drafted then or now, and every file whose working-tree diff
    moved, set against the text the earlier review saw - written to since.diff,
    each listed with its changed lines and how its earlier text was got."""
    now = {draft.relative_to(drafts).as_posix(): draft for draft in drafted}
    marked = (earlier / "review.md").read_text(encoding="utf-8").split(
        "## drafts against the repository", 1)
    then = {match[1] for line in (marked[1].split("\n## ", 1)[0] if len(marked) > 1 else "")
            .splitlines() if (match := DRAFT_LINE.match(line))}
    before = diff_sections((earlier / "worktree.diff").read_text(encoding="utf-8"))
    after = diff_sections((out / "worktree.diff").read_text(encoding="utf-8"))
    moved = {named[2:] for named in set(before) ^ set(after)
             | {named for named in before if before[named] != after.get(named)}
             if named.startswith("b/")}
    lines, diffs = [f"## since {earlier.name} (since.diff)", ""], []
    for relative in sorted(set(now) | then | moved):
        current = now.get(relative, REPO / relative)
        try:
            text, how = earlier_text(relative, earlier)
        except Exception as failure:  # noqa: BLE001 - one file's failure is listed
            lines.append(f"  FAILED  {relative}: {failure}")
            continue
        if text is None or not current.exists():
            lines.append(f"  {'UNKNOWN' if text is None else 'GONE'}  {relative}: {how}")
            continue
        kept = out / "earlier" / relative
        kept.parent.mkdir(parents=True, exist_ok=True)
        kept.write_text(text, encoding="utf-8", newline="\n")
        _, printed = run(["git", "--no-optional-locks", "diff", "--no-index", "--",
                          str(kept), str(current)], REPO, 60)
        lines.append(f"{changed_lines(printed):5}  {relative}  ({how})")
        diffs.append(printed)
    (out / "since.diff").write_text("\n".join(diffs), encoding="utf-8")
    return [*lines, ""]


def review(drafts: Path, earlier: Path | None = None) -> None:
    """The working tree against HEAD and every draft against the repository's
    own file, each kept as a diff; the recordings left out, as the commits step
    leaves them. Untracked code is listed rather than diffed - there is nothing
    to set it against - and kept, with the drafts and HEAD, for a later review
    to set itself against; the judge's scripts are linted, as a capture's run
    lints them."""
    out = REVIEWS / time.strftime("%Y%m%d-%H%M%S", time.gmtime())
    out.mkdir(parents=True)
    outside = f":(exclude){RECORDINGS.relative_to(REPO).as_posix()}"
    (out / "head.txt").write_text(git("rev-parse", "HEAD") + "\n", encoding="utf-8")
    (out / "worktree.diff").write_text(git("diff", "HEAD", "--", ".", outside) + "\n",
                                       encoding="utf-8")
    lines = ["# Review", "", "## tracked, against HEAD (worktree.diff)", "",
             git("diff", "HEAD", "--stat=200", "--", ".", outside) or "no change", ""]
    untracked = [line[3:] for line in git("status", "--porcelain", "--untracked-files=all")
                 .splitlines() if line.startswith("?? ") and line[3:].startswith(CODE)]
    lines += ["## untracked code", "", *(untracked or ["none"]), ""]
    for relative in untracked:
        if relative.endswith(".py"):
            kept = out / "untracked" / relative
            kept.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(REPO / relative, kept)
    drafted = ([] if drafts == REPO else
               sorted(path for path in drafts.rglob("*")
                      if path.is_file() and "__pycache__" not in path.parts))
    lines += ["## drafts against the repository (drafts.diff)", ""]
    diffs = []
    for draft in drafted:
        relative = draft.relative_to(drafts).as_posix()
        kept = out / "drafts" / relative
        kept.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(draft, kept)
        ours = REPO / relative
        if not ours.exists():
            lines.append(f"  NEW  {relative}")
            continue
        _, printed = run(["git", "--no-optional-locks", "diff", "--no-index", "--",
                          str(ours), str(draft)], REPO, 60)
        lines.append(f"{changed_lines(printed):5}  {relative}")
        diffs.append(printed)
    (out / "drafts.diff").write_text("\n".join(diffs), encoding="utf-8")
    if earlier:
        lines += ["", *since_section(drafts, drafted, earlier, out)]
    status, printed = run([PYTHON, "-m", "ruff", "check", "--no-cache", "--output-format",
                           "concise", str(SCRIPTS)], REPO, 120)
    lines += ["", "## script lint", "", f"ruff {status}", *printed.splitlines()]
    (out / "review.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"review: {out / 'review.md'}")


def main(argv: list[str]) -> None:
    if len(argv) < 2:
        print(__doc__)
        sys.exit(2)
    if argv[1] == "resume":
        status, printed = run([PYTHON, "-B", "-X", "utf8", str(SCRIPTS / "resume.py"), *argv[2:]],
                              REPO, 300)
        print(printed, end="")
        if status != "exit 0":
            sys.exit(f"resume.py {status}")
        return
    first = Path(argv[1]).resolve()
    earlier = Path(argv[2]).resolve() if len(argv) == 3 else None
    if ((len(argv) == 2 or (earlier and (earlier / "review.md").exists()))
            and (first == REPO or (first / "modules").is_dir() or (first / "tests").is_dir())):
        review(first, earlier)
        return
    capture = first
    baselines = [Path(arg).resolve() for arg in argv[2:]]
    for folder in [capture, *baselines]:
        if not (folder / "replay_log.json").exists():
            print(f"{folder} holds no replay_log.json - pass a captured test's own folder")
            sys.exit(2)
    judge = Judge(capture, baselines)
    write_up = str(capture / "write_up_request.json")

    judge.step("recording set", lambda: step_recording_set(judge))
    judge.step("calls", lambda: step_calls(judge))
    judge.step("calls vs baseline", lambda: step_calls_against_baselines(judge))
    judge.step("answers", lambda: step_answers(judge))
    judge.step("diverged", lambda: step_diverged(judge))
    judge.step("recorded vs asked", lambda: step_recorded_against_asked(judge))
    judge.step("pages", lambda: step_pages(judge))
    judge.step("pages vs baseline", lambda: step_pages_against_baselines(judge))
    judge.step("pdf vs page", lambda: step_pdf_against_page(judge))
    judge.step("leaks", lambda: step_leaks(judge))
    judge.step("slack", lambda: step_slack(judge))
    judge.step("record", lambda: step_record(judge))
    judge.step("figures", helper(judge, "check_figures.py", str(capture), keep="figures.txt"))
    judge.step("tokens", helper(judge, "tokens_of.py", str(capture), keep="tokens.txt"))
    judge.step("loss", helper(judge, "recompute_loss.py", str(capture), keep="loss.txt"))
    judge.step("sets", helper(judge, "sets_by_hand.py", str(capture), keep="sets.txt"))
    judge.step("rows", helper(judge, "brief_rows.py", write_up, keep="rows.txt"))
    judge.step("inputs", helper(judge, "write_up_inputs.py", write_up, str(judge.out / "inputs")))
    judge.step("review", helper(judge, "review_of.py", str(capture), keep="review.txt"))
    judge.step("cost", lambda: step_cost(judge))
    judge.step("exchange", lambda: step_exchange(judge))
    judge.step("fields", lambda: step_fields(judge))
    judge.step("change steps", lambda: step_change_steps(judge))
    judge.step("blobs", lambda: step_blobs(judge))
    judge.step("commits", lambda: step_commits(judge))
    judge.step("script lint", lambda: step_lint(judge))

    named = [judge.label(baseline) for baseline in baselines] or "none"
    head = (f"# Judge report: {capture.parent.name}/{capture.name}\n\n"
            f"Baselines: {named}\n"
            f"Every step's whole output is under judge/.\n\n")
    report = capture / "judge-report.md"
    if report.exists():
        kept = (capture / f"judge-report-{number}.md" for number in range(1, 1000))
        report.rename(next(path for path in kept if not path.exists()))
    report.write_text(head + "\n".join(judge.sections), encoding="utf-8")
    print(f"report: {report}")


if __name__ == "__main__":
    main(sys.argv)
