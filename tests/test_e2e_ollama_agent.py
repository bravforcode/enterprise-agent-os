"""End-to-end test: real agent + Ollama LLM."""
import asyncio
import sys
sys.path.insert(0, "src")
from graxia_tool.llm import OllamaClient
from graxia_tool.agents import AGENT_REGISTRY, get_agent


async def test():
    print("Available agents:", len(AGENT_REGISTRY))
    for name in ["coder", "researcher", "general"]:
        cls = get_agent(name)
        if cls:
            print(f"  - {name}: {cls.description}")

    print()
    print("Running general agent with Ollama...")
    agent = get_agent("general")
    llm = OllamaClient(default_model="llama3.2:1b")

    async def llm_func(prompt, system=None, **kwargs):
        resp = await llm.complete(prompt=prompt, system=system, max_tokens=200)
        return resp.content

    agent.llm_func = llm_func
    result = await agent.run("Say hello in one short sentence.")
    print(f"Success: {result.success}")
    output = result.output if isinstance(result.output, str) else str(result.output)[:300]
    print(f"Output: {output}")
    cost = result.cost_usd
    print(f"Cost: ${cost:.4f}")
    print(f"Duration: {result.duration_ms}ms")
    await llm.close()


asyncio.run(test())
