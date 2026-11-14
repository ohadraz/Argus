"""Each saved page as text, and every link on it checked: an anchor must name
an id the page holds, ids must be unique and never "None", a local route must
answer 200 from the held stack. Then every link into Argus the last opening's
Slack posts carry - the synopsis PDF is linked from nowhere else - fetched the
same way.

usage: check_pages.py <capture dir> <out dir> [base url]
"""

import json
import re
import sys
import urllib.request
from collections import Counter
from html.parser import HTMLParser
from pathlib import Path

PAGES = ("postmortem_page", "walk_page", "incident_page")
_BLOCKS = ("p", "li", "tr", "h1", "h2", "h3", "h4", "div", "br", "section")

# Argus's address in the e2e stack, and so the held stack's: the default base.
HELD_STACK = "http://localhost:8000"

# A link as Slack carries it: <address|what it says>, or <address> alone.
_SLACK_LINK = re.compile(r"<(https?://[^|>\s]+)(?:\|[^>]*)?>")


class Page(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.ids: list[str] = []
        self.links: list[tuple[str, str]] = []
        self.text: list[str] = []
        self._href: str | None = None
        self._anchor: list[str] = []
        self._skip = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        found = dict(attrs)
        if found.get("id"):
            self.ids.append(found["id"] or "")
        if tag in ("script", "style"):
            self._skip += 1
        if tag == "a" and found.get("href") is not None:
            self._href, self._anchor = found["href"], []
        if tag in _BLOCKS:
            self.text.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag in ("script", "style"):
            self._skip -= 1
        if tag == "a" and self._href is not None:
            self.links.append((self._href, "".join(self._anchor).strip()))
            self._href = None
        if tag in ("td", "th"):
            self.text.append(" | ")

    def handle_data(self, data: str) -> None:
        if self._skip:
            return
        self.text.append(data)
        if self._href is not None:
            self._anchor.append(data)


def status(url: str) -> str:
    try:
        with urllib.request.urlopen(url, timeout=10) as answer:
            return str(answer.status)
    except Exception as error:  # noqa: BLE001 - the reason is the report
        return f"FAILED {error}"


def slack_routes(capture: Path, base: str) -> list[str]:
    """The last opening's links into Argus, each path fetched from `base`: the
    host in a post is config, not judged, and an earlier opening's incident is
    gone from the stack."""
    source = capture / "slack_posted.json"
    if not source.exists():
        return ["== slack: not saved"]

    posted = json.loads(source.read_text(encoding="utf-8"))["posted"]
    starts = [i for i, message in enumerate(posted)
              if message["text"].startswith("Argus: Received")]
    routes: dict[str, str] = {}
    for message in posted[starts[-1]:] if starts else posted:
        for address in _SLACK_LINK.findall(message["text"]):
            if address.startswith(HELD_STACK):
                path = address[len(HELD_STACK):]
                routes.setdefault(path, status(base + path))

    report = [f"== slack: {len(routes)} links into Argus from the last opening"]
    report += [f"  {verdict}: {path}" for path, verdict in routes.items() if verdict != "200"]
    report.append(f"  local routes: {routes}")
    return report


def main() -> None:
    capture, out = Path(sys.argv[1]), Path(sys.argv[2])
    base = sys.argv[3] if len(sys.argv) > 3 else HELD_STACK
    out.mkdir(parents=True, exist_ok=True)

    for name in PAGES:
        source = capture / f"{name}.html"
        if not source.exists():
            print(f"== {name}: not saved")
            continue

        page = Page()
        page.feed(source.read_text(encoding="utf-8"))
        lines = [" ".join(line.split()) for line in "".join(page.text).splitlines()]
        (out / f"{name}.txt").write_text("\n".join(line for line in lines if line),
                                         encoding="utf-8")

        held = set(page.ids)
        external = 0
        report = [f"== {name}: {len(page.links)} links, {len(held)} ids"]
        repeated = [an_id for an_id, count in Counter(page.ids).items() if count > 1]
        if repeated:
            report.append(f"  REPEATED IDS: {repeated}")
        if any("None" in an_id for an_id in held):
            report.append("  AN ID SAYS None")

        routes: dict[str, str] = {}
        for href, said in page.links:
            if href.startswith("#"):
                verdict = "ok" if href[1:] in held else "DEAD ANCHOR"
            elif href.startswith("/"):
                path = href.split("#")[0]
                routes.setdefault(path, status(base + path))
                verdict = routes[path]
            else:
                external += 1
                continue
            if verdict not in ("ok", "200"):
                report.append(f"  {verdict}: {href}  [{said[:60]}]")

        report.append(f"  external links (not fetched): {external}")
        report.append(f"  local routes: {routes}")
        print("\n".join(report))

    print("\n".join(slack_routes(capture, base)))


if __name__ == "__main__":
    main()
