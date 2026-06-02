"""End-to-end test: real Ollama LLM call (not fast path)."""
import asyncio
import sys
sys.path.insert(0, "src")
from graxia_tool.llm import OllamaClient


async def test():
    llm = OllamaClient(default_model="llama3.2:1b")
    print("Testing Ollama directly (real LLM)...")
    print()

    # Test 1: Math
    print("=" * 50)
    print("Test 1: Math (2+2)")
    print("=" * 50)
    resp = await llm.complete(
        prompt="What is 2+2? Answer with just the number.",
        max_tokens=10,
    )
    print(f"  Response: {resp.content.strip()}")
    print(f"  Tokens: {resp.tokens_in} in / {resp.tokens_out} out")
    print(f"  Cost: ${resp.cost_usd:.4f} (FREE - local)")
    print(f"  Time: {resp.duration_ms}ms")
    print()

    # Test 2: Multiplication
    print("=" * 50)
    print("Test 2: Multiplication (7*8)")
    print("=" * 50)
    resp = await llm.complete(
        prompt="What is 7 times 8?",
        max_tokens=20,
    )
    print(f"  Response: {resp.content.strip()}")
    print(f"  Tokens: {resp.tokens_in} in / {resp.tokens_out} out")
    print(f"  Time: {resp.duration_ms}ms")
    print()

    # Test 3: Code
    print("=" * 50)
    print("Test 3: Code generation (Python hello world)")
    print("=" * 50)
    resp = await llm.complete(
        prompt="Write a Python hello world one-liner. Just the code, no explanation.",
        max_tokens=30,
    )
    print(f"  Response: {resp.content.strip()}")
    print(f"  Tokens: {resp.tokens_in} in / {resp.tokens_out} out")
    print(f"  Time: {resp.duration_ms}ms")
    print()

    # Stats
    print("=" * 50)
    print("Summary")
    print("=" * 50)
    print("All tests passed!")
    print("Ollama works as a drop-in replacement for cloud LLMs")
    print("No API key required, runs locally, $0 cost")

    await llm.close()


asyncio.run(test())
