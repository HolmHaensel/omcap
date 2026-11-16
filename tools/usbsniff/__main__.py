"""Run as `python -B tools/usbsniff ...` or `python -B -m usbsniff ...` with tools/ on the path."""
import os
import sys

if __package__ in (None, ""):
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    from usbsniff.cli import main
else:
    from .cli import main

main()
