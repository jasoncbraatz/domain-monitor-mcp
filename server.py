#!/usr/bin/env python3
"""Backward-compatible entry point.

If you installed via pip, use the `domain-monitor-mcp` command instead.
This file is kept for users who cloned the repo directly.
"""
from domain_monitor_mcp.server import main

if __name__ == "__main__":
    main()
