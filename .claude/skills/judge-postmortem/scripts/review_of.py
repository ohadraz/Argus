"""Prints the stored review criteria of each capture's postmortem row.

usage: review_of.py <capture test dir>...
"""

import json
import sys
from pathlib import Path

for folder in map(Path, sys.argv[1:]):
    rows = json.loads((folder / "db" / "postmortem.json").read_text(encoding="utf-8"))
    rows = rows if isinstance(rows, list) else rows.get("rows", [rows])
    for row in rows:
        review = row.get("review")
        review = json.loads(review) if isinstance(review, str) else review
        print(f"== {folder.parent.name}/{folder.name}")
        for criterion in review or []:
            print(f"   {criterion.get('criterion')}: met={criterion.get('met')}"
                  f"{' - ' + criterion['because'] if criterion.get('because') else ''}")
