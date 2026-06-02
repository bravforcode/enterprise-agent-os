"""Quick test of AutoRouter, SessionMemory, ContextCache."""
import sys
sys.path.insert(0, "src")

from graxia_tool.auto_router import AutoRouter
from graxia_tool.session_memory import SessionMemory, TaskRecord, CodebaseKnowledge
from graxia_tool.context_cache import ContextCache

def test_auto_router():
    router = AutoRouter()
    tests = [
        ("Write a Python function to parse CSV files", "code", "coder"),
        ("Fix the bug in auth.py that causes 500 errors", "debug", "debugger"),
        ("Search for latest OpenAI API documentation", "research", "researcher"),
        ("Research how to implement OAuth2", "research", "researcher"),
        ("Deploy the application to production", "deploy", "deployer"),
        ("Write unit tests for the user service", "test", "tester"),
        ("Review this pull request for security issues", "review", "reviewer"),
        ("Explain how the caching layer works", "document", "documenter"),
    ]
    passed = 0
    for prompt, exp_intent, exp_agent in tests:
        d = router.route(prompt)
        ok = d.intent == exp_intent and d.agent_type == exp_agent
        status = "PASS" if ok else "FAIL"
        if ok:
            passed += 1
        print(f"  {status}: intent={d.intent} (exp {exp_intent}), agent={d.agent_type} (exp {exp_agent})")
    print(f"  AutoRouter: {passed}/{len(tests)} passed")
    return passed == len(tests)

def test_session_memory():
    mem = SessionMemory()  # in-memory
    # Store a task
    task = TaskRecord(prompt="Fix auth bug", success=True, agent_type="debugger", intent="debug")
    tid = mem.remember_task(task)
    assert tid, "Task ID should not be empty"
    # Recall
    results = mem.recall("auth bug")
    assert len(results) > 0, "Should recall the task"
    assert results[0].memory_type == "task"
    # Store preference
    mem.remember_preference("terse_mode", "true")
    val = mem.get_preference("terse_mode")
    assert val == "true", f"Expected 'true', got '{val}'"
    # Codebase knowledge
    kb = CodebaseKnowledge(path="src/auth.py", summary="Authentication module", patterns=["JWT"])
    mem.remember_codebase(kb)
    results = mem.recall_codebase("auth")
    assert len(results) > 0, "Should recall codebase"
    # Summary
    summary = mem.get_session_summary()
    assert summary.total_tasks == 1
    mem.close()
    print("  SessionMemory: ALL PASS")
    return True

def test_context_cache():
    cache = ContextCache()  # in-memory
    # Store
    decision = {"intent": "code", "agent_type": "coder", "skills": ["rtk-tdd"]}
    cache.set("Write a function", decision, {"output": "done"})
    # Retrieve exact match
    cached = cache.get("Write a function")
    assert cached is not None, "Cache hit expected"
    assert cached.decision["intent"] == "code"
    # Semantic match (similar keywords)
    cached2 = cache.get("Write a Python function")
    # May or may not match depending on keyword overlap, that's OK
    # Stats
    stats = cache.get_stats()
    assert stats["cached_contexts"] >= 1
    assert stats["hits"] >= 1
    cache.close()
    print("  ContextCache: ALL PASS")
    return True

if __name__ == "__main__":
    results = []
    results.append(("AutoRouter", test_auto_router()))
    results.append(("SessionMemory", test_session_memory()))
    results.append(("ContextCache", test_context_cache()))
    print()
    all_ok = all(r[1] for r in results)
    print(f"Overall: {'ALL PASS' if all_ok else 'SOME FAILED'}")
    for name, ok in results:
        print(f"  {name}: {'PASS' if ok else 'FAIL'}")
