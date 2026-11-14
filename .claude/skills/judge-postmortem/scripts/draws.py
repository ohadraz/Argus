"""N draws of one write-up call through the claude CLI on the subscription, in
parallel: the input dir's system prompt in place of Claude Code's, no tools,
the tool's description beside it as the API gives it, and the tool's input
schema as the structured output it must return.

The CLI is `claude` on PATH, or CLAUDE_CLI where it is not.

usage: draws.py <input dir> <out dir> [n]
       (input dir holds brief.txt, tool.json and system.txt - write_up_inputs.py)
"""

import json
import os
import shutil
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

MODEL = "claude-opus-5-5"
# The write-up asks at high; the grounding judge at medium - DRAWS_EFFORT=medium draws it as asked.
EFFORT = os.environ.get("DRAWS_EFFORT", "high")


def the_cli() -> str:
    found = os.environ.get("CLAUDE_CLI") or shutil.which("claude")
    if found is None:
        sys.exit("no claude CLI: put it on PATH or set CLAUDE_CLI")
    return found


def draw(cli: str, source: Path, out: Path, started: float) -> None:
    tool = json.loads((source / "tool.json").read_text(encoding="utf-8"))
    system = ((source / "system.txt").read_text(encoding="utf-8")
              + f"\n\nYour answer is the arguments of the tool {tool['name']}, which is described "
                f"as follows:\n{tool['description']}")

    done = subprocess.run(
        [cli, "-p", "--model", MODEL, "--effort", EFFORT,
         "--system-prompt", system, "--tools", "", "--safe-mode",
         "--no-session-persistence", "--output-format", "json",
         "--json-schema", json.dumps(tool["input_schema"])],
        input=(source / "brief.txt").read_text(encoding="utf-8"),
        capture_output=True, text=True, encoding="utf-8", cwd=out.parent)

    result = json.loads(done.stdout) if done.stdout.strip().startswith("{") else None
    answer = (result or {}).get("structured_output")
    elapsed = f"[{time.time() - started:5.0f}s]"

    if answer is None:
        out.with_suffix(".error.txt").write_text(
            f"{done.returncode}\n{done.stdout}\n{done.stderr}", encoding="utf-8")
        print(f"{elapsed} {out.name}: FAILED, see {out.with_suffix('.error.txt').name}", flush=True)
        return

    out.with_suffix(".json").write_text(json.dumps(answer, indent=1, ensure_ascii=False),
                                        encoding="utf-8")
    print(f"{elapsed} {out.name}: ok, cost {result.get('total_cost_usd')}", flush=True)


def main() -> None:
    source, target = Path(sys.argv[1]), Path(sys.argv[2])
    n = int(sys.argv[3]) if len(sys.argv) > 3 else 5
    target.mkdir(parents=True, exist_ok=True)
    cli = the_cli()
    started = time.time()

    with ThreadPoolExecutor(max_workers=n) as pool:
        for k in range(1, n + 1):
            pool.submit(draw, cli, source, target / f"W{k}", started)

    print(f"all done in {time.time() - started:.0f}s", flush=True)


if __name__ == "__main__":
    main()
