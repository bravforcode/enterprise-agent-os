import asyncio
import sys
sys.path.insert(0, r"C:\Users\menum\enterprise-agent-os\src")
from graxia_tool.llm import HybridLLMClient

async def t():
    c = HybridLLMClient()
    r = await c.complete("Say hi in 5 words exactly", max_tokens=30)
    print("OK:", r.content[:120])
    print("Model:", r.model)
    print("Tokens:", r.tokens_in, "in /", r.tokens_out, "out")
    if hasattr(c, "close"):
        await c.close()

asyncio.run(t())
