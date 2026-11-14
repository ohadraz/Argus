"""N draws of one recorded write-up call against the real Anthropic API, in
parallel: the recorded request body exactly as Argus sent it (model, system,
tools, thinking, effort), with only the brief - the first message - replaced.

Spends API credit: report each run's cost, and subtract it from the ledger.
The key is read from the repo's .env (ANTHROPIC_API_KEY) and never printed.

usage: api_draws.py <recording.request.json> <brief.txt> <out dir> [n]
"""

import json
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import httpx

URL = "https://api.anthropic.com/v1/messages"
REPO = Path(__file__).resolve().parents[4]
# Opus 5.5, per million tokens.
PRICE = {"input_tokens": 4.0, "cache_creation_input_tokens": 5.0,
         "cache_read_input_tokens": 0.20, "output_tokens": 20.0}


def the_key() -> str:
    for line in (REPO / ".env").read_text(encoding="utf-8").splitlines():
        if line.startswith("ANTHROPIC_API_KEY="):
            return line.split("=", 1)[1].strip().strip('"')
    sys.exit("no ANTHROPIC_API_KEY in .env")


def cost_of(usage: dict) -> float:
    return sum(usage.get(field, 0) * per for field, per in PRICE.items()) / 1_000_000


def draw(body: dict, key: str, out: Path, started: float) -> float:
    answered = httpx.post(URL, json=body, timeout=600, headers={
        "x-api-key": key, "anthropic-version": "2023-06-01", "content-type": "application/json"})
    elapsed = f"[{time.time() - started:5.0f}s]"

    if answered.status_code != 200:
        out.with_suffix(".error.txt").write_text(answered.text, encoding="utf-8")
        print(f"{elapsed} {out.name}: FAILED {answered.status_code}", flush=True)
        return 0.0

    message = answered.json()
    # Kept whole: an answer with no tool call says why only here (stop_reason, text).
    out.with_suffix(".raw.json").write_text(json.dumps(message, indent=1, ensure_ascii=False),
                                            encoding="utf-8")
    usage = message.get("usage", {})
    answer = next((block["input"] for block in message["content"]
                   if block["type"] == "tool_use"), None)
    out.with_suffix(".json").write_text(json.dumps(answer, indent=1, ensure_ascii=False),
                                        encoding="utf-8")
    spent = cost_of(usage)
    print(f"{elapsed} {out.name}: ok, ${spent:.3f}", flush=True)
    return spent


def main() -> None:
    request, brief, target = Path(sys.argv[1]), Path(sys.argv[2]), Path(sys.argv[3])
    n = int(sys.argv[4]) if len(sys.argv) > 4 else 5
    target.mkdir(parents=True, exist_ok=True)

    body = json.loads(request.read_text(encoding="utf-8"))
    body["messages"] = [{"role": "user", "content": brief.read_text(encoding="utf-8")}]
    key = the_key()
    started = time.time()

    with ThreadPoolExecutor(max_workers=n) as pool:
        spent = list(pool.map(lambda k: draw(body, key, target / f"W{k}", started),
                              range(1, n + 1)))

    print(f"all done in {time.time() - started:.0f}s, spent ${sum(spent):.2f}", flush=True)


if __name__ == "__main__":
    main()
