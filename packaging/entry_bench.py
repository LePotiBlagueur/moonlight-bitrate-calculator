"""Script gelé : mesure complète + rapport."""

import multiprocessing
import sys

from moonlight_bitrate.entry import bench_main

if __name__ == "__main__":
    multiprocessing.freeze_support()
    sys.exit(bench_main())
