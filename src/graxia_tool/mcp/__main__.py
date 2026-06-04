"""Entry point: python -m graxia_tool.mcp"""
import sys
import asyncio

if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

from . import main

if __name__ == "__main__":
    sys.exit(main())
