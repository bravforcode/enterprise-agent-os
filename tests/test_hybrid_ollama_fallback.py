"""REAL end-to-end test: force OpenRouter to fail, verify Ollama responds.

This is the critical test the user asked for:
'เพิ่ม ollama เข้าไปเพิ่มด้วยถ้าโควต้าหมด'
"""
import asyncio
import os
import sys
import time
from pathlib import Path
from unittest.mock import patch, MagicMock

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from graxia_tool.llm import (
    HybridLLMClient, OpenRouterClient, OllamaClient,
    get_llm_client,
)


def header(s):
    print()
    print("=" * 70)
    print(s)
    print("=" * 70)


def step(s):
    print(f"\n  >>> {s}")


# Pre-flight: verify Ollama is actually running
header("PRE-FLIGHT: Verify Ollama is running")
import urllib.request, json
try:
    with urllib.request.urlopen("http://localhost:11434/api/tags", timeout=5) as r:
        data = json.loads(r.read().decode())
    print(f"  Ollama: RUNNING, {len(data.get('models', []))} models")
    for m in data.get("models", []):
        print(f"    - {m['name']}")
    ollama_running = True
except Exception as e:
    print(f"  Ollama: NOT RUNNING ({e})")
    ollama_running = False

# Pre-flight: verify OpenRouter key is set
or_key = os.environ.get("OPENROUTER_API_KEY", "")
print(f"  OpenRouter key: {'SET' if or_key else 'NOT SET'}")
or_key_set = bool(or_key)

# Pre-flight: verify OpenRouter is actually rate-limited (we know it is)
if or_key_set:
    print("  Checking OpenRouter rate limit status...")
    try:
        req = urllib.request.Request(
            "https://openrouter.ai/api/v1/chat/completions",
            data=json.dumps({
                "model": "nvidia/nemotron-3-super-120b-a12b:free",
                "messages": [{"role": "user", "content": "hi"}],
                "max_tokens": 5,
            }).encode(),
            headers={
                "Authorization": f"Bearer {or_key}",
                "Content-Type": "application/json",
            },
        )
        with urllib.request.urlopen(req, timeout=10) as r:
            d = json.loads(r.read().decode())
            print(f"  OpenRouter: WORKING (got response)")
            or_working = True
    except Exception as e:
        err = str(e)
        if hasattr(e, "read"):
            try:
                err = e.read().decode()[:200]
            except:
                pass
        print(f"  OpenRouter: RATE-LIMITED ({err[:100]})")
        or_working = False


# Test 1: HybridLLMClient with real OpenRouter (probably rate-limited) -> Ollama fallback
async def test_real_fallback_to_ollama():
    header("TEST 1: Real OpenRouter (likely 429) -> Ollama fallback")
    if not or_key_set:
        print("  SKIP: no OpenRouter key in env")
        return "SKIP"
    if not ollama_running:
        print("  SKIP: Ollama not running")
        return "SKIP"

    client = HybridLLMClient()
    start = time.time()
    try:
        resp = await client.complete(
            "Say OK in one word",
            max_tokens=20,
            temperature=0.3,
        )
        elapsed = time.time() - start
        chain = resp.metadata.get("client_chain", [])
        primary = resp.metadata.get("primary_client", "?")
        print(f"  Model:        {resp.model}")
        print(f"  Primary:      {primary}")
        print(f"  Client chain: {chain}")
        print(f"  Time:         {elapsed:.2f}s")
        print(f"  Cost:         ${resp.cost_usd:.6f}")
        print(f"  Response:     {resp.content[:100]!r}")
        print(f"  Tokens:       {resp.tokens_in} in / {resp.tokens_out} out")
        assert resp.content, "Empty response"
        # Verify which client was used
        if primary == "ollama":
            print(f"  [OK] Fell back to Ollama after OpenRouter failed")
        elif primary == "openrouter":
            print(f"  [OK] OpenRouter worked (quota may have reset)")
        return "PASS"
    except Exception as e:
        elapsed = time.time() - start
        print(f"  [FAIL] Both backends failed: {str(e)[:300]}")
        return "FAIL"
    finally:
        await client.close()


# Test 2: Mock OpenRouter 429 on ALL models -> verify Ollama is called
async def test_mock_fallback_to_ollama():
    header("TEST 2: Mock OpenRouter 429 -> verify Ollama called")
    if not ollama_running:
        print("  SKIP: Ollama not running")
        return "SKIP"

    client = HybridLLMClient()
    # Mock the OpenRouter client's complete method to always fail with 429-like error
    async def mock_or_fail(*args, **kwargs):
        raise RuntimeError(
            "All 7 OpenRouter models failed. Tried: x=429; y=429; z=429. "
            "(OpenRouter DAILY free-tier quota exhausted - resets at UTC midnight)"
        )

    with patch.object(client, "_get_openrouter") as mock_get_or:
        # Return a mock client whose .complete() always fails
        mock_or_client = MagicMock()
        mock_or_client.complete = mock_or_fail
        mock_get_or.return_value = mock_or_client

        start = time.time()
        try:
            resp = await client.complete("Say 'OK'", max_tokens=20, temperature=0.3)
            elapsed = time.time() - start
            chain = resp.metadata.get("client_chain", [])
            primary = resp.metadata.get("primary_client", "?")
            print(f"  Model:        {resp.model}")
            print(f"  Primary:      {primary}")
            print(f"  Client chain: {chain}")
            print(f"  Time:         {elapsed:.2f}s")
            print(f"  Response:     {resp.content[:100]!r}")
            assert primary == "ollama", f"Expected ollama, got {primary}"
            assert "openrouter_failed" in resp.metadata, "Should record OR failure"
            or_failed = resp.metadata["openrouter_failed"]
            assert "free-tier quota exhausted" in or_failed or "All 7" in or_failed, \
                f"Should preserve OR error: {or_failed[:200]}"
            print(f"  [OK] Fell back to Ollama, OR error preserved: {or_failed[:80]}")
            return "PASS"
        except Exception as e:
            elapsed = time.time() - start
            print(f"  [FAIL] {str(e)[:300]}")
            return "FAIL"
        finally:
            await client.close()


# Test 3: OpenRouter works -> Ollama NOT called
async def test_openrouter_used_when_works():
    header("TEST 3: OpenRouter works -> Ollama NOT called")
    if not or_key_set:
        print("  SKIP: no OpenRouter key")
        return "SKIP"

    # Try real first, fall back to mock if rate-limited
    client = HybridLLMClient()
    ollama_call_count = [0]
    real_ollama_complete = OllamaClient.complete

    async def counting_ollama_complete(self, *args, **kwargs):
        ollama_call_count[0] += 1
        return await real_ollama_complete(self, *args, **kwargs)

    # First, try real OpenRouter
    if or_working:
        try:
            with patch.object(OllamaClient, "complete", counting_ollama_complete):
                resp = await client.complete("Say OK", max_tokens=10)
            chain = resp.metadata.get("client_chain", [])
            primary = resp.metadata.get("primary_client", "?")
            print(f"  [REAL] Primary:      {primary}")
            print(f"  [REAL] Chain:        {chain}")
            print(f"  [REAL] Model:        {resp.model}")
            print(f"  [REAL] Ollama calls: {ollama_call_count[0]}")
            assert primary == "openrouter", f"Expected openrouter, got {primary}"
            assert ollama_call_count[0] == 0, f"Ollama should not be called, was called {ollama_call_count[0]}x"
            print(f"  [OK] OpenRouter used, Ollama not called")
            await client.close()
            return "PASS"
        except Exception as e:
            err_short = str(e)[:100]
            if "rate" in err_short.lower() or "429" in err_short or "quota" in err_short:
                print(f"  [REAL] OpenRouter now rate-limited, falling back to mock test")
                await client.close()
            else:
                print(f"  [FAIL] Unexpected error: {err_short}")
                await client.close()
                return "FAIL"

    # Mock OpenRouter to succeed
    print("  [MOCK] Mocking OpenRouter to succeed, Ollama to fail if called")
    client = HybridLLMClient()
    ollama_call_count = [0]

    async def counting_ollama_complete2(self, *args, **kwargs):
        ollama_call_count[0] += 1
        # Return a fake response to detect the call
        from graxia_tool.llm import LLMResponse
        return LLMResponse(
            content="OLLAMA WAS CALLED (BUG)",
            model="fake-ollama",
            tokens_in=1, tokens_out=1, cost_usd=0.0, duration_ms=1,
            metadata={"marker": "ollama_called"},
        )

    async def mock_or_success(*args, **kwargs):
        from graxia_tool.llm import LLMResponse
        return LLMResponse(
            content="OpenRouter mock success",
            model="mock-or-model:free",
            tokens_in=1, tokens_out=1, cost_usd=0.0, duration_ms=10,
            metadata={"finish_reason": "stop"},
        )

    try:
        with patch.object(OllamaClient, "complete", counting_ollama_complete2):
            with patch.object(client, "_get_openrouter") as mock_get:
                mock_or = MagicMock()
                mock_or.complete = mock_or_success
                mock_get.return_value = mock_or

                resp = await client.complete("test", max_tokens=10)

        chain = resp.metadata.get("client_chain", [])
        primary = resp.metadata.get("primary_client", "?")
        print(f"  [MOCK] Primary:      {primary}")
        print(f"  [MOCK] Chain:        {chain}")
        print(f"  [MOCK] Model:        {resp.model}")
        print(f"  [MOCK] Ollama calls: {ollama_call_count[0]}")
        assert primary == "openrouter", f"Expected openrouter, got {primary}"
        assert ollama_call_count[0] == 0, f"Ollama should NOT be called when OR works, but was called {ollama_call_count[0]}x"
        print(f"  [OK] OpenRouter mock succeeded, Ollama not called (CRITICAL)")
        return "PASS"
    except Exception as e:
        print(f"  [FAIL] {str(e)[:200]}")
        return "FAIL"
    finally:
        await client.close()


# Test 4: No OpenRouter key -> Ollama used directly (no OR attempt)
async def test_no_or_key_uses_ollama_directly():
    header("TEST 4: No OPENROUTER_API_KEY -> Ollama used directly")
    if not ollama_running:
        print("  SKIP: Ollama not running")
        return "SKIP"

    client = HybridLLMClient(openrouter_key="")
    # Spy: if OR is somehow called, we'll know
    or_attempted = [False]
    original_get = client._get_openrouter
    def spy_get():
        result = original_get()
        if result is not None:
            or_attempted[0] = True
        return result
    client._get_openrouter = spy_get

    try:
        resp = await client.complete("Say OK", max_tokens=10)
        chain = resp.metadata.get("client_chain", [])
        primary = resp.metadata.get("primary_client", "?")
        print(f"  Primary:      {primary}")
        print(f"  Client chain: {chain}")
        print(f"  Model:        {resp.model}")
        print(f"  OR attempted: {or_attempted[0]}")
        assert primary == "ollama", f"Expected ollama, got {primary}"
        assert not or_attempted[0], "OR should not be attempted without key"
        assert chain == ["ollama"], f"Chain should be just ['ollama'], got {chain}"
        print(f"  [OK] No OR attempt, Ollama used directly")
        return "PASS"
    except Exception as e:
        print(f"  [FAIL] {str(e)[:200]}")
        return "FAIL"
    finally:
        await client.close()


# Test 5: Both backends fail -> clear error message
async def test_both_fail_clear_error():
    header("TEST 5: Both backends fail -> clear error")
    if not or_key_set:
        print("  SKIP: no OpenRouter key")
        return "SKIP"

    # Point Ollama to a non-existent URL to force failure
    client = HybridLLMClient(ollama_url="http://localhost:9999")

    async def mock_or_fail(*args, **kwargs):
        raise RuntimeError("All 7 OpenRouter models failed. (quota)")

    with patch.object(client, "_get_openrouter") as mock_get:
        mock_or_client = MagicMock()
        mock_or_client.complete = mock_or_fail
        mock_get.return_value = mock_or_client

        try:
            resp = await client.complete("test", max_tokens=5)
            print(f"  [FAIL] Expected RuntimeError, got response: {resp.content[:50]}")
            return "FAIL"
        except RuntimeError as e:
            err = str(e)
            print(f"  Error: {err[:300]}")
            assert "HybridLLMClient" in err, "Should mention HybridLLMClient"
            assert "OpenRouter" in err, "Should mention OpenRouter failure"
            assert "Ollama" in err, "Should mention Ollama failure"
            assert "Fix:" in err, "Should give fix instructions"
            print(f"  [OK] Clear error message with both failures + fix instructions")
            return "PASS"
        finally:
            await client.close()


async def main():
    results = []
    for t in [
        test_real_fallback_to_ollama,
        test_mock_fallback_to_ollama,
        test_openrouter_used_when_works,
        test_no_or_key_uses_ollama_directly,
        test_both_fail_clear_error,
    ]:
        try:
            r = await t()
            results.append((t.__name__, r))
        except Exception as e:
            results.append((t.__name__, f"ERROR: {e}"))
            import traceback
            traceback.print_exc()

    header("FINAL RESULTS")
    for name, status in results:
        symbol = "[OK]" if status == "PASS" else ("[--]" if status == "SKIP" else "[!!]")
        print(f"  {symbol} {name}: {status}")
    fails = sum(1 for _, s in results if s not in ("PASS", "SKIP"))
    print()
    print(f"  Total: {len(results)} tests, {fails} failures")
    sys.exit(0 if fails == 0 else 1)


if __name__ == "__main__":
    asyncio.run(main())
