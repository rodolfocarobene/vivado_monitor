"""PyInstaller entry point (vmon/__main__.py uses relative imports, so it cannot be the script)."""
import multiprocessing
import sys

from vmon.cli import main

if __name__ == "__main__":
    multiprocessing.freeze_support()
    sys.exit(main())
