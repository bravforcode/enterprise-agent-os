"""Debug: run the failing test in isolation."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

# Run phase9_14 first
print("Running phase9_14 tests...")
import subprocess
result = subprocess.run(
    [sys.executable, "-m", "pytest", "tests/test_phase9_14.py", "-q", "--tb=short"],
    capture_output=True, text=True
)
print("phase9_14 stdout:", result.stdout[-500:])
print("phase9_14 stderr:", result.stderr[-500:])

# Now test the web endpoint
print("\nNow testing web endpoint...")
from fastapi.testclient import TestClient
from graxia_tool.web import app
client = TestClient(app)
r = client.post("/api/agents/run", json={"agent": "coder", "query": "test"})
print(f"Status: {r.status_code}")
print(f"Body: {r.text[:500]}")
