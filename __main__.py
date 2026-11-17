"""Lanceur sans installation : `python __main__.py [options]`.

`python __main__.py recap ...` bascule sur la CLI récapitulative.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from moonlight_bitrate.entry import bench_main, recap_main  # noqa: E402

if __name__ == "__main__":
    argv = sys.argv[1:]
    if argv and argv[0] == "recap":
        raise SystemExit(recap_main(argv[1:]))
    raise SystemExit(bench_main(argv))
