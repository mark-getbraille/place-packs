"""The program's start for PyInstaller (the installed PhotoLocationIdentifier.exe): the same as python -m pli."""

import sys

from pli.cli import main

if __name__ == "__main__":
    sys.exit(main())
