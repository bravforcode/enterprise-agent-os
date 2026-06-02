"""Fine-tuning data export and training pipeline.

Exports agent interactions in formats suitable for fine-tuning:
- OpenAI fine-tune format (JSONL)
- Anthropic fine-tune format
- Custom JSONL for ONNX training

Collects from:
- Agent call history (in-memory or Postgres)
- Audit logs
- Cache hit/miss patterns
"""
from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional


@dataclass
class TrainingExample:
    """Single training example for fine-tuning."""
    prompt: str
    completion: str
    agent: str
    model: str
    tokens_in: int = 0
    tokens_out: int = 0
    cost_usd: float = 0.0
    metadata: dict[str, Any] = field(default_factory=dict)
    timestamp: float = field(default_factory=time.time)

    def to_openai_format(self) -> dict:
        """Convert to OpenAI fine-tune format."""
        return {
            "messages": [
                {"role": "user", "content": self.prompt},
                {"role": "assistant", "content": self.completion},
            ]
        }

    def to_anthropic_format(self) -> dict:
        """Convert to Anthropic fine-tune format."""
        return {
            "prompt": f"\n\nHuman: {self.prompt}\n\nAssistant:",
            "completion": f" {self.completion}",
        }

    def to_simple_format(self) -> dict:
        """Convert to simple JSONL format."""
        return {
            "prompt": self.prompt,
            "completion": self.completion,
            "agent": self.agent,
            "model": self.model,
        }


class TrainingDataCollector:
    """Collects training examples from agent runs."""

    def __init__(self):
        self.examples: list[TrainingExample] = []

    def add_example(
        self,
        prompt: str,
        completion: str,
        agent: str,
        model: str = "unknown",
        tokens_in: int = 0,
        tokens_out: int = 0,
        cost_usd: float = 0.0,
        metadata: Optional[dict] = None,
    ) -> TrainingExample:
        """Add a training example."""
        example = TrainingExample(
            prompt=prompt,
            completion=completion,
            agent=agent,
            model=model,
            tokens_in=tokens_in,
            tokens_out=tokens_out,
            cost_usd=cost_usd,
            metadata=metadata or {},
        )
        self.examples.append(example)
        return example

    def add_from_agent_result(
        self,
        agent: str,
        query: str,
        output: Any,
        model: str = "unknown",
        tokens_in: int = 0,
        tokens_out: int = 0,
        cost_usd: float = 0.0,
    ) -> TrainingExample:
        """Add training example from agent result."""
        # Extract completion from output dict
        # Use agent-specific output key first, then generic
        if isinstance(output, dict):
            # 1. Try agent-specific key (e.g., tester -> "tests")
            agent_output_key = self._get_agent_output_key(agent)
            if agent_output_key in output and output[agent_output_key]:
                completion = output[agent_output_key]
            else:
                # 2. Fall back to priority order
                priority_keys = [
                    "code", "review", "tests", "test_cases", "summary",
                    "response", "analysis", "report", "audit", "config",
                    "sql", "design", "result", "text", "content"
                ]
                completion = None
                for key in priority_keys:
                    if key in output and output[key]:
                        completion = output[key]
                        break
                if completion is None:
                    completion = json.dumps(output)
        else:
            completion = str(output)

        return self.add_example(
            prompt=query,
            completion=completion,
            agent=agent,
            model=model,
            tokens_in=tokens_in,
            tokens_out=tokens_out,
            cost_usd=cost_usd,
        )

    @staticmethod
    def _get_agent_output_key(agent: str) -> str:
        """Get the primary output key for an agent."""
        agent_keys = {
            "coder": "code",
            "tester": "tests",
            "reviewer": "review",
            "researcher": "summary",
            "documenter": "summary",
            "data_engineer": "sql",
            "security_auditor": "audit",
            "architect": "design",
            "network_engineer": "config",
            "database_admin": "sql",
            "frontend_designer": "code",
        }
        return agent_keys.get(agent, "output")

    def get_count(self) -> int:
        """Get number of examples."""
        return len(self.examples)

    def get_by_agent(self, agent: str) -> list[TrainingExample]:
        """Get examples for specific agent."""
        return [e for e in self.examples if e.agent == agent]

    def get_by_model(self, model: str) -> list[TrainingExample]:
        """Get examples for specific model."""
        return [e for e in self.examples if e.model == model]

    def filter_quality(
        self,
        min_tokens_out: int = 10,
        max_cost: float = 0.10,
    ) -> list[TrainingExample]:
        """Filter for high-quality examples."""
        return [
            e for e in self.examples
            if e.tokens_out >= min_tokens_out and e.cost_usd <= max_cost
        ]

    def clear(self):
        """Clear all examples."""
        self.examples = []


class TrainingDataExporter:
    """Export training data to various formats."""

    @staticmethod
    def to_jsonl(
        examples: list[TrainingExample],
        output_path: str,
        format_type: str = "openai",
    ) -> int:
        """Export examples to JSONL file.

        Args:
            examples: List of training examples
            output_path: Output file path
            format_type: One of 'openai', 'anthropic', 'simple'

        Returns:
            Number of examples written
        """
        path = Path(output_path)
        path.parent.mkdir(parents=True, exist_ok=True)

        with open(path, "w", encoding="utf-8") as f:
            for ex in examples:
                if format_type == "openai":
                    line = ex.to_openai_format()
                elif format_type == "anthropic":
                    line = ex.to_anthropic_format()
                else:
                    line = ex.to_simple_format()
                f.write(json.dumps(line, ensure_ascii=False) + "\n")

        return len(examples)

    @staticmethod
    def to_csv(examples: list[TrainingExample], output_path: str) -> int:
        """Export to CSV (for analysis)."""
        import csv

        path = Path(output_path)
        path.parent.mkdir(parents=True, exist_ok=True)

        with open(path, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(
                f,
                fieldnames=["prompt", "completion", "agent", "model", "tokens_in", "tokens_out", "cost_usd", "timestamp"]
            )
            writer.writeheader()
            for ex in examples:
                writer.writerow({
                    "prompt": ex.prompt[:500],
                    "completion": ex.completion[:500],
                    "agent": ex.agent,
                    "model": ex.model,
                    "tokens_in": ex.tokens_in,
                    "tokens_out": ex.tokens_out,
                    "cost_usd": ex.cost_usd,
                    "timestamp": ex.timestamp,
                })

        return len(examples)

    @staticmethod
    def export_split(
        examples: list[TrainingExample],
        output_dir: str,
        train_ratio: float = 0.8,
        format_type: str = "openai",
    ) -> dict[str, int]:
        """Split and export train/val datasets."""
        output = Path(output_dir)
        output.mkdir(parents=True, exist_ok=True)

        # Shuffle
        import random
        shuffled = examples.copy()
        random.shuffle(shuffled)

        # Split
        split_idx = int(len(shuffled) * train_ratio)
        train = shuffled[:split_idx]
        val = shuffled[split_idx:]

        # Export
        train_path = output / "train.jsonl"
        val_path = output / "val.jsonl"

        TrainingDataExporter.to_jsonl(train, str(train_path), format_type)
        TrainingDataExporter.to_jsonl(val, str(val_path), format_type)

        return {
            "train": len(train),
            "val": len(val),
            "total": len(examples),
        }


# Singleton
_collector: Optional[TrainingDataCollector] = None


def get_training_collector() -> TrainingDataCollector:
    """Get global training data collector."""
    global _collector
    if _collector is None:
        _collector = TrainingDataCollector()
    return _collector
