"""Entry point: python -m graxia_tool.mcp

Optimized for fast startup:
1. Uses daemon mode if DAEMON=1 env var is set
2. Falls back to single-use mode otherwise
"""
import sys
import asyncio
import os

if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

# Check if daemon mode is requested
if os.environ.get("GRAXIA_DAEMON") == "1":
    from .daemon import main
    sys.exit(main())
else:
    from . import main
    sys.exit(main())
