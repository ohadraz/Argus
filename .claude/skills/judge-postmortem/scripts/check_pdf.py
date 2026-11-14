"""The saved PDF as text, and its links: every internal destination must
resolve; each URI is listed once.

usage: check_pdf.py <capture dir> <out dir>
"""

import sys
from pathlib import Path

from pypdf import PdfReader


def main() -> None:
    capture, out = Path(sys.argv[1]), Path(sys.argv[2])
    out.mkdir(parents=True, exist_ok=True)

    reader = PdfReader(capture / "postmortem.pdf")
    (out / "postmortem_pdf.txt").write_text(
        "\n".join(page.extract_text() or "" for page in reader.pages), encoding="utf-8")
    # The executive synopsis, where the incident wrote one: as text, for the diff
    # against the baseline - the overview's words reach no page.
    synopsis = capture / "synopsis.pdf"
    if synopsis.exists():
        (out / "synopsis_pdf.txt").write_text(
            "\n".join(page.extract_text() or "" for page in PdfReader(synopsis).pages),
            encoding="utf-8")

    named = set(reader.named_destinations)
    uris: list[str] = []
    internal = 0
    broken: list[tuple[int, str]] = []

    for number, page in enumerate(reader.pages, 1):
        for annotation in page.get("/Annots") or []:
            found = annotation.get_object()
            if found.get("/Subtype") != "/Link":
                continue
            action = found.get("/A")
            action = action.get_object() if action is not None else None
            if action is not None and action.get("/URI"):
                uris.append(str(action["/URI"]))
                continue
            destination = found.get("/Dest") or (action.get("/D") if action is not None else None)
            if destination is None:
                broken.append((number, repr(found)[:80]))
                continue
            internal += 1
            if isinstance(destination, str) and destination not in named:
                broken.append((number, destination))

    print(f"pages {len(reader.pages)}, internal links {internal}, uri links {len(uris)}, "
          f"broken {broken}")
    for uri in sorted(set(uris)):
        print(" ", uri)


if __name__ == "__main__":
    main()
