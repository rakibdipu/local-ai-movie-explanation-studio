#!/usr/bin/env python3
"""Root entry point for Local AI Movie Explanation Studio."""

import os
import sys

# Ensure repository root is on sys.path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app.main import cli

if __name__ == "__main__":
    cli()
