#!/usr/bin/env python3
"""Compat launcher: `python rh_sniper.py` → same as `rh-sniper`."""

from rh_sniper.cli import main

if __name__ == "__main__":
    main()
