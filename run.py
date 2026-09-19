#!/usr/bin/env python3
"""Run with Python 3.11+ on Linux. No pip packages or GPU setup required."""
import sys

if sys.version_info < (3, 11):
    raise SystemExit("Python 3.11 이상이 필요합니다.")

from mafia.server import main

if __name__ == "__main__":
    main()
