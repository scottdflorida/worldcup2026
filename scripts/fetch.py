#!/usr/bin/env python3
"""Fetch the latest World Cup 2026 data into the local cache."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from wc import data  # noqa: E402

if __name__ == "__main__":
    data.refresh()
