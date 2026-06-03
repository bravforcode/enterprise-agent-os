import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from graxia_tool.rag import RAGEngine
from graxia_tool.session_memory import SessionMemory, TaskRecord


def test_memory_recall_during_query():
    mem = SessionMemory(":memory:")
    mem.remember_task(TaskRecord(
        task_id="past-1", prompt="what is the revenue forecast",
        routing_decision={}, outcome="Revenue forecast is $1.2M for Q2",
        success=True, duration_ms=1000, tokens_used=500,
        agent_type="researcher", intent="research",
    ))

    eng = RAGEngine(memory=mem)
    result = eng.query("what is the revenue?", top_k=3, rerank=False)

    assert "results" in result, "Missing 'results' key"
    assert len(result["results"]) > 0, "Expected at least 1 result"
    mem_result = result["results"][0]
    assert mem_result["source"] == "memory", f"Expected source=memory, got {mem_result['source']}"
    assert mem_result["score"] > 0.5, f"Expected score > 0.5, got {mem_result['score']}"
    assert "revenue" in result["context"].lower(), "Context should mention revenue"
    print("  PASS: test_memory_recall_during_query")


def test_set_memory_method():
    mem = SessionMemory(":memory:")
    eng = RAGEngine()
    eng.set_memory(mem)
    assert eng.memory is mem, "set_memory should attach the memory instance"
    print("  PASS: test_set_memory_method")


def test_memory_optional_backward_compat():
    eng = RAGEngine()
    assert eng.memory is None, "Default memory should be None"
    result = eng.query("hello", top_k=2, rerank=False)
    assert "results" in result
    assert "context" in result
    print("  PASS: test_memory_optional_backward_compat")


def test_memory_in_constructor():
    mem = SessionMemory(":memory:")
    eng = RAGEngine(memory=mem)
    assert eng.memory is mem, "__init__ should accept memory parameter"
    print("  PASS: test_memory_in_constructor")


def test_memory_merges_with_retrieval():
    mem = SessionMemory(":memory:")
    mem.remember_task(TaskRecord(
        task_id="past-2", prompt="deploy the application",
        routing_decision={}, outcome="Deployed successfully to production",
        success=True, duration_ms=5000, tokens_used=1000,
        agent_type="deployer", intent="deploy",
    ))

    eng = RAGEngine(memory=mem)
    result = eng.query("deploy application", top_k=3, rerank=False)

    assert len(result["results"]) > 0
    has_memory = any(r["source"] == "memory" for r in result["results"])
    assert has_memory, "Expected at least one memory-sourced result"
    mem_entry = next(r for r in result["results"] if r["source"] == "memory")
    assert "/deployer)" in mem_entry["citation"], "Citation should include agent_type"
    print("  PASS: test_memory_merges_with_retrieval")


def test_low_confidence_memory_excluded():
    mem = SessionMemory(":memory:")
    mem.remember_task(TaskRecord(
        task_id="past-3", prompt="completely unrelated topic about gardening",
        routing_decision={}, outcome="Planted tomatoes",
        success=True, duration_ms=100, tokens_used=50,
        agent_type="researcher", intent="research",
    ))

    eng = RAGEngine(memory=mem)
    result = eng.query("revenue forecast", top_k=3, rerank=False)

    mem_results = [r for r in result["results"] if r["source"] == "memory"]
    assert len(mem_results) == 0, "Low-confidence memory should be excluded"
    print("  PASS: test_low_confidence_memory_excluded")


if __name__ == "__main__":
    tests = [
        test_memory_recall_during_query,
        test_set_memory_method,
        test_memory_optional_backward_compat,
        test_memory_in_constructor,
        test_memory_merges_with_retrieval,
        test_low_confidence_memory_excluded,
    ]
    passed = 0
    for t in tests:
        try:
            t()
            passed += 1
        except Exception as e:
            print(f"  FAIL: {t.__name__}: {e}")
    total = len(tests)
    print(f"\nResults: {passed}/{total} passed")
    sys.exit(0 if passed == total else 1)
