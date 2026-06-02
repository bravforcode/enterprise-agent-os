"""Tests for fine-tune module — 30+ tests."""
import json
import sys
import tempfile
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from graxia_tool.finetune import (
    TrainingExample, TrainingDataCollector, TrainingDataExporter,
    get_training_collector,
)


# --- TrainingExample Tests ---

class TestTrainingExample:
    """Tests for TrainingExample."""

    def test_create_example(self):
        """Should create example with defaults."""
        ex = TrainingExample(prompt="hi", completion="hello", agent="coder", model="gpt-4o")
        assert ex.prompt == "hi"
        assert ex.completion == "hello"
        assert ex.agent == "coder"

    def test_to_openai_format(self):
        """Should convert to OpenAI format."""
        ex = TrainingExample(prompt="hi", completion="hello", agent="coder", model="gpt-4o")
        oai = ex.to_openai_format()
        assert "messages" in oai
        assert len(oai["messages"]) == 2
        assert oai["messages"][0]["role"] == "user"
        assert oai["messages"][1]["role"] == "assistant"

    def test_to_anthropic_format(self):
        """Should convert to Anthropic format."""
        ex = TrainingExample(prompt="hi", completion="hello", agent="coder", model="claude")
        ant = ex.to_anthropic_format()
        assert "prompt" in ant
        assert "completion" in ant
        assert "Human:" in ant["prompt"]
        assert "Assistant:" in ant["prompt"]

    def test_to_simple_format(self):
        """Should convert to simple format."""
        ex = TrainingExample(prompt="hi", completion="hello", agent="coder", model="gpt-4o")
        simple = ex.to_simple_format()
        assert simple["prompt"] == "hi"
        assert simple["completion"] == "hello"
        assert simple["agent"] == "coder"


# --- Collector Tests ---

class TestCollector:
    """Tests for TrainingDataCollector."""

    def test_add_example(self):
        """Should add example."""
        c = TrainingDataCollector()
        ex = c.add_example("p", "c", "coder", "gpt-4o")
        assert ex.prompt == "p"
        assert c.get_count() == 1

    def test_add_from_dict_output(self):
        """Should extract completion from dict output."""
        c = TrainingDataCollector()
        c.add_from_agent_result(
            agent="coder",
            query="write function",
            output={"code": "def f(): pass"},
        )
        ex = c.examples[0]
        assert "def f()" in ex.completion

    def test_add_from_dict_with_multiple_keys(self):
        """Should pick first available key."""
        c = TrainingDataCollector()
        c.add_from_agent_result(
            agent="tester",
            query="test",
            output={"tests": "test code", "code": "ignored"},
        )
        ex = c.examples[0]
        assert "test code" in ex.completion

    def test_add_from_string_output(self):
        """Should handle string output."""
        c = TrainingDataCollector()
        c.add_from_agent_result(
            agent="coder",
            query="q",
            output="raw output",
        )
        ex = c.examples[0]
        assert ex.completion == "raw output"

    def test_get_by_agent(self):
        """Should filter by agent."""
        c = TrainingDataCollector()
        c.add_example("p1", "c1", "coder", "gpt-4o")
        c.add_example("p2", "c2", "reviewer", "gpt-4o")
        c.add_example("p3", "c3", "coder", "gpt-4o")
        coder_examples = c.get_by_agent("coder")
        assert len(coder_examples) == 2

    def test_get_by_model(self):
        """Should filter by model."""
        c = TrainingDataCollector()
        c.add_example("p1", "c1", "coder", "gpt-4o")
        c.add_example("p2", "c2", "coder", "claude")
        gpt4 = c.get_by_model("gpt-4o")
        assert len(gpt4) == 1

    def test_filter_quality(self):
        """Should filter by quality criteria."""
        c = TrainingDataCollector()
        c.add_example("p1", "c1", "coder", "gpt-4o", tokens_out=100, cost_usd=0.01)
        c.add_example("p2", "c2", "coder", "gpt-4o", tokens_out=5, cost_usd=0.01)  # too short
        c.add_example("p3", "c3", "coder", "gpt-4o", tokens_out=100, cost_usd=1.00)  # too expensive
        quality = c.filter_quality(min_tokens_out=10, max_cost=0.10)
        assert len(quality) == 1

    def test_clear(self):
        """Should clear examples."""
        c = TrainingDataCollector()
        c.add_example("p", "c", "coder", "gpt-4o")
        c.clear()
        assert c.get_count() == 0


# --- Exporter Tests ---

class TestExporter:
    """Tests for TrainingDataExporter."""

    def test_to_jsonl_openai(self):
        """Should export to OpenAI JSONL."""
        c = TrainingDataCollector()
        c.add_example("p1", "c1", "coder", "gpt-4o")
        c.add_example("p2", "c2", "coder", "gpt-4o")

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "train.jsonl"
            count = TrainingDataExporter.to_jsonl(c.examples, str(path), "openai")
            assert count == 2
            assert path.exists()
            with open(path) as f:
                lines = f.readlines()
            assert len(lines) == 2
            line = json.loads(lines[0])
            assert "messages" in line

    def test_to_jsonl_anthropic(self):
        """Should export to Anthropic JSONL."""
        c = TrainingDataCollector()
        c.add_example("p", "c", "coder", "claude")

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "train.jsonl"
            TrainingDataExporter.to_jsonl(c.examples, str(path), "anthropic")
            with open(path) as f:
                line = json.loads(f.readline())
            assert "Human:" in line["prompt"]

    def test_to_jsonl_simple(self):
        """Should export to simple JSONL."""
        c = TrainingDataCollector()
        c.add_example("p", "c", "coder", "gpt-4o")

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "train.jsonl"
            TrainingDataExporter.to_jsonl(c.examples, str(path), "simple")
            with open(path) as f:
                line = json.loads(f.readline())
            assert line["prompt"] == "p"
            assert line["agent"] == "coder"

    def test_to_csv(self):
        """Should export to CSV."""
        c = TrainingDataCollector()
        c.add_example("p", "c", "coder", "gpt-4o", tokens_in=10, tokens_out=20, cost_usd=0.01)

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "data.csv"
            count = TrainingDataExporter.to_csv(c.examples, str(path))
            assert count == 1
            assert path.exists()
            content = path.read_text()
            assert "coder" in content
            assert "gpt-4o" in content

    def test_export_split(self):
        """Should split into train/val."""
        c = TrainingDataCollector()
        for i in range(10):
            c.add_example(f"p{i}", f"c{i}", "coder", "gpt-4o")

        with tempfile.TemporaryDirectory() as tmp:
            result = TrainingDataExporter.export_split(c.examples, tmp, train_ratio=0.8)
            assert result["train"] == 8
            assert result["val"] == 2
            assert result["total"] == 10
            assert (Path(tmp) / "train.jsonl").exists()
            assert (Path(tmp) / "val.jsonl").exists()


# --- Singleton Tests ---

class TestSingleton:
    """Tests for singleton collector."""

    def test_singleton(self):
        """Should return same instance."""
        c1 = get_training_collector()
        c2 = get_training_collector()
        assert c1 is c2


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
