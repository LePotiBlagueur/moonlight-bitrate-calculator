"""Script gelé : tableau récapitulatif."""

import multiprocessing
import sys

from moonlight_bitrate.entry import recap_main

if __name__ == "__main__":
    multiprocessing.freeze_support()
    sys.exit(recap_main())
