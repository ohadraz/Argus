"""`python -m apps.worker`: the worker process, as `process.main` starts it."""

from __future__ import annotations

from apps.worker.process import main

if __name__ == "__main__":
    main()
