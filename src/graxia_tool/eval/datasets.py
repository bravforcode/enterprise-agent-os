"""Golden evaluation datasets for regression testing.

Each dataset contains test cases with expected outputs.
Used by the eval framework for continuous quality monitoring.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .framework import EvalCase, keyword_match, contains_match, similarity_match


@dataclass
class GoldenDataset:
    """A named collection of eval cases."""
    name: str
    description: str
    cases: list[EvalCase] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)


# ============================================================
# Code Generation Dataset
# ============================================================

CODE_GENERATION_CASES = [
    EvalCase(
        name="code-001",
        input="Write a Python function to compute factorial of n",
        expected="def factorial(n):\n    if n <= 1: return 1\n    return n * factorial(n-1)",
        evaluator=contains_match,
        tags=["python", "recursion"],
    ),
    EvalCase(
        name="code-002",
        input="Write a Python function to check if a string is a palindrome",
        expected="def is_palindrome(s): return s == s[::-1]",
        evaluator=keyword_match(["palindrome", "def", "return"]),
        tags=["python", "string"],
    ),
    EvalCase(
        name="code-003",
        input="Write a Python function to flatten a nested list",
        expected="def flatten(lst): return [item for sub in lst for item in (flatten(sub) if isinstance(sub, list) else [sub])]",
        evaluator=keyword_match(["flatten", "list", "def"]),
        tags=["python", "recursion", "list"],
    ),
    EvalCase(
        name="code-004",
        input="Write a Python function to find the nth Fibonacci number",
        expected="def fib(n): a, b = 0, 1; [a, b] = [b, a+b] for _ in range(n); return a",
        evaluator=keyword_match(["fibonacci", "def", "return"]),
        tags=["python", "iteration"],
    ),
    EvalCase(
        name="code-005",
        input="Write a JavaScript function to debounce another function",
        expected="function debounce(fn, ms) { let timeout; return (...args) => { clearTimeout(timeout); timeout = setTimeout(() => fn(...args), ms); }; }",
        evaluator=keyword_match(["debounce", "setTimeout", "function"]),
        tags=["javascript", "async"],
    ),
]

CODE_GENERATION = GoldenDataset(
    name="code_generation",
    description="Code generation tasks across Python and JavaScript",
    cases=CODE_GENERATION_CASES,
)


# ============================================================
# Question Answering Dataset
# ============================================================

QA_CASES = [
    EvalCase(
        name="qa-001",
        input="What is the capital of France?",
        expected="Paris",
        evaluator=contains_match,
        tags=["geography", "factual"],
    ),
    EvalCase(
        name="qa-002",
        input="What is 2 + 2?",
        expected="4",
        evaluator=contains_match,
        tags=["math"],
    ),
    EvalCase(
        name="qa-003",
        input="Who wrote Romeo and Juliet?",
        expected="William Shakespeare",
        evaluator=contains_match,
        tags=["literature"],
    ),
    EvalCase(
        name="qa-004",
        input="What is the largest planet in our solar system?",
        expected="Jupiter",
        evaluator=contains_match,
        tags=["science", "astronomy"],
    ),
    EvalCase(
        name="qa-005",
        input="Explain photosynthesis in one sentence",
        expected="Plants convert sunlight, water, and carbon dioxide into glucose and oxygen",
        evaluator=keyword_match(["sunlight", "water", "carbon dioxide", "oxygen"]),
        tags=["science", "biology"],
    ),
    EvalCase(
        name="qa-006",
        input="What is machine learning?",
        expected="A method of data analysis that automates analytical model building using algorithms that learn from data",
        evaluator=keyword_match(["algorithm", "data", "learn"]),
        tags=["ai", "ml"],
    ),
]

QA = GoldenDataset(
    name="qa",
    description="Question answering across multiple domains",
    cases=QA_CASES,
)


# ============================================================
# Reasoning Dataset
# ============================================================

REASONING_CASES = [
    EvalCase(
        name="reason-001",
        input="If all roses are flowers, and some flowers fade quickly, can we conclude that some roses fade quickly?",
        expected="No, we cannot conclude this. The premise only says some flowers fade, not that the subset includes roses.",
        evaluator=keyword_match(["no", "cannot"]),
        tags=["logic"],
    ),
    EvalCase(
        name="reason-002",
        input="A bat and ball cost $1.10 in total. The bat costs $1.00 more than the ball. How much does the ball cost?",
        expected="5 cents",
        evaluator=contains_match,
        tags=["math", "cognitive-bias"],
    ),
    EvalCase(
        name="reason-003",
        input="If it takes 5 machines 5 minutes to make 5 widgets, how long would it take 100 machines to make 100 widgets?",
        expected="5 minutes",
        evaluator=contains_match,
        tags=["math", "logic"],
    ),
]

REASONING = GoldenDataset(
    name="reasoning",
    description="Logical reasoning and math word problems",
    cases=REASONING_CASES,
)


# ============================================================
# Summarization Dataset
# ============================================================

SUMMARIZATION_CASES = [
    EvalCase(
        name="sum-001",
        input="Summarize: The Industrial Revolution was a period of major industrialization that began in Great Britain in the late 1700s and spread to other parts of Europe and North America. It marked a shift from agrarian and handicraft economies to industrial and machine-based production.",
        expected="The Industrial Revolution began in Britain in the late 1700s, shifting economies from agrarian to industrial.",
        evaluator=keyword_match(["Industrial Revolution", "Britain", "industrial"]),
        tags=["summary"],
    ),
    EvalCase(
        name="sum-002",
        input="Summarize: Climate change refers to long-term shifts in temperatures and weather patterns. Since the 1800s, human activities have been the main driver of climate change, primarily due to burning fossil fuels like coal, oil, and gas, which releases greenhouse gases into the atmosphere.",
        expected="Climate change, driven mainly by human fossil fuel use since the 1800s, causes long-term temperature and weather shifts.",
        evaluator=keyword_match(["climate", "fossil", "human"]),
        tags=["summary", "science"],
    ),
]

SUMMARIZATION = GoldenDataset(
    name="summarization",
    description="Text summarization tasks",
    cases=SUMMARIZATION_CASES,
)


# ============================================================
# Translation Dataset
# ============================================================

TRANSLATION_CASES = [
    EvalCase(
        name="trans-001",
        input="Translate to Spanish: 'Hello, how are you?'",
        expected="Hola, ¿cómo estás?",
        evaluator=keyword_match(["Hola"]),
        tags=["translation", "spanish"],
    ),
    EvalCase(
        name="trans-002",
        input="Translate to French: 'Good morning'",
        expected="Bonjour",
        evaluator=contains_match,
        tags=["translation", "french"],
    ),
    EvalCase(
        name="trans-003",
        input="Translate to Thai: 'Thank you very much'",
        expected="ขอบคุณมาก",
        evaluator=keyword_match(["ขอบคุณ"]),
        tags=["translation", "thai"],
    ),
]

TRANSLATION = GoldenDataset(
    name="translation",
    description="Translation across multiple languages",
    cases=TRANSLATION_CASES,
)


# ============================================================
# All datasets
# ============================================================

ALL_DATASETS: dict[str, GoldenDataset] = {
    "code_generation": CODE_GENERATION,
    "qa": QA,
    "reasoning": REASONING,
    "summarization": SUMMARIZATION,
    "translation": TRANSLATION,
}


def get_dataset(name: str) -> GoldenDataset:
    """Get a dataset by name."""
    if name not in ALL_DATASETS:
        raise KeyError(f"Dataset {name!r} not found. Available: {list(ALL_DATASETS.keys())}")
    return ALL_DATASETS[name]


def list_datasets() -> list[str]:
    """List all available dataset names."""
    return list(ALL_DATASETS.keys())


def get_total_case_count() -> int:
    """Total number of test cases across all datasets."""
    return sum(len(ds.cases) for ds in ALL_DATASETS.values())
