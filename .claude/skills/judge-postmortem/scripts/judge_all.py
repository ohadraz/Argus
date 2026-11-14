"""Run judge_case.py over every test folder in a capture set against one baseline.

usage: judge_all.py <capture set dir> <out root> <baseline text dir>
"""

import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).parent
PYTHON = Path(r"C:\Users\ohadr\Projects\Argus\.venv\Scripts\python.exe")
NOISE = ("FAILED", "external links", "local routes", "Traceback", "File \"", "~~~",
         "self.", "raise ", "reader = ", "main()", "line = ", "pypdf.errors")


def main() -> None:
    captures, out_root, baseline = (Path(arg) for arg in sys.argv[1:4])

    for case in sorted(p for p in captures.iterdir() if p.is_dir()):
        print(f"\n########## {case.name}", flush=True)
        done = subprocess.run([str(PYTHON), "-X", "utf8", str(HERE / "judge_case.py"),
                               str(case), str(out_root / case.name), str(baseline)],
                              capture_output=True, text=True, encoding="utf-8")
        for line in (done.stdout + done.stderr).splitlines():
            if not any(noise in line for noise in NOISE):
                print(line)


if __name__ == "__main__":
    main()
