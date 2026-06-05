"""Cost optimizer with token budget tracking, model routing, and cache-first policy."""

import hashlib
import json
import sqlite3
import time
from dataclasses import dataclass, field
from typing import Any, Dict, Optional, Tuple


# Model pricing per 1K tokens (input + output)
MODEL_PRICING: Dict[str, Dict[str, float]] = {
    "small": {"input": 0.0008, "output": 0.002},
    "medium": {"input": 0.003, "output": 0.015},
    "large": {"input": 0.015, "output": 0.075},
}

# Complexity thresholds for routing
COMPLEXITY_SMALL_MAX = 0.3
COMPLEXITY_MEDIUM_MAX = 0.7


@dataclass
class CostConfig:
    """Configuration for cost optimization."""

    db_path: str = "graxia_cost.db"
    daily_token_limit: int = 1_000_000
    daily_cost_limit: float = 10.0
    session_cost_ceiling: float = 1.0
    cache_ttl_hours: float = 24.0
    default_model: str = "medium"


@dataclass
class TokenUsage:
    """Token usage for a single call."""

    model: str
    input_tokens: int
    output_tokens: int
    cached: bool
    cost_usd: float
    timestamp: float = field(default_factory=time.time)


class CostOptimizer:
    """Cost optimizer with budget tracking, model routing, and caching.

    Features:
    - Token budget tracking (daily limit)
    - Model routing by task complexity
    - Cache-first policy (skip LLM if cached)
    - Cost ceiling per session
    - Stats: total tokens, total cost, savings from cache
    """

    def __init__(self, config: Optional[CostConfig] = None):
        self.config = config or CostConfig()
        self.conn = sqlite3.connect(self.config.db_path)
        self.conn.row_factory = sqlite3.Row
        self._init_db()

        self._session_cost: float = 0.0
        self._session_start: float = time.time()

    def _init_db(self) -> None:
        """Initialize database tables."""
        self.conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS usage_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp REAL NOT NULL,
                model TEXT NOT NULL,
                input_tokens INTEGER NOT NULL,
                output_tokens INTEGER NOT NULL,
                cached INTEGER NOT NULL,
                cost_usd REAL NOT NULL,
                cache_key TEXT,
                session_id TEXT
            );

            CREATE TABLE IF NOT EXISTS cache_store (
                cache_key TEXT PRIMARY KEY,
                response TEXT NOT NULL,
                model TEXT NOT NULL,
                tokens_used INTEGER NOT NULL,
                created_at REAL NOT NULL,
                expires_at REAL NOT NULL,
                hit_count INTEGER DEFAULT 0
            );

            CREATE INDEX IF NOT EXISTS idx_usage_timestamp ON usage_log(timestamp);
            CREATE INDEX IF NOT EXISTS idx_cache_expires ON cache_store(expires_at);
            """
        )
        self.conn.commit()

    def _cache_key(self, prompt: str, model: str) -> str:
        """Generate a cache key from prompt + model."""
        raw = f"{model}:{prompt}"
        return hashlib.sha256(raw.encode()).hexdigest()[:32]

    def estimate_tokens(self, text: str) -> int:
        """Rough token estimate (words * 1.3)."""
        return max(1, int(len(text.split()) * 1.3))

    def estimate_complexity(self, prompt: str) -> float:
        """Estimate task complexity from prompt characteristics.

        Returns value between 0.0 (simple) and 1.0 (complex).
        """
        score = 0.0
        words = prompt.split()
        word_count = len(words)

        if word_count > 200:
            score += 0.3
        elif word_count > 100:
            score += 0.2
        elif word_count > 50:
            score += 0.1
        elif word_count < 20:
            score -= 0.1

        code_indicators = [
            "implement", "refactor", "debug", "architect", "design",
            "algorithm", "optimize", "parallel", "concurrent", "async",
            "database", "schema", "migrate", "deploy", "pipeline",
            "test", "coverage", "integration", "authentication", "security",
            "distributed", "consensus", "fault", "tolerance", "recovery",
            "replication", "leader", "election", "state", "machine",
            "threading", "mutex", "semaphore", "queue", "cache",
            "injection", "encryption", "protocol", "handshake", "token",
            "microservice", "container", "orchestration", "cluster", "scaling",
        ]
        prompt_lower = prompt.lower()
        matches = sum(1 for ind in code_indicators if ind in prompt_lower)
        score += min(matches * 0.08, 0.7)

        if any(w in prompt_lower for w in ["write", "list", "show", "what", "how many"]):
            score -= 0.15

        if "?" in prompt:
            score -= 0.05

        return max(0.0, min(1.0, score))

    def route_model(self, prompt: str, preferred: Optional[str] = None) -> str:
        """Route to the appropriate model based on task complexity.

        Args:
            prompt: The task prompt.
            preferred: Override complexity routing.

        Returns:
            Model name: 'small', 'medium', or 'large'.
        """
        if preferred and preferred in MODEL_PRICING:
            return preferred

        complexity = self.estimate_complexity(prompt)

        if complexity <= COMPLEXITY_SMALL_MAX:
            return "small"
        elif complexity <= COMPLEXITY_MEDIUM_MAX:
            return "medium"
        else:
            return "large"

    def cache_get(self, prompt: str, model: str) -> Optional[str]:
        """Check cache for a matching response.

        Returns cached response or None.
        """
        key = self._cache_key(prompt, model)
        now = time.time()

        row = self.conn.execute(
            "SELECT response, expires_at FROM cache_store WHERE cache_key = ?",
            (key,),
        ).fetchone()

        if row and row["expires_at"] > now:
            self.conn.execute(
                "UPDATE cache_store SET hit_count = hit_count + 1 WHERE cache_key = ?",
                (key,),
            )
            self.conn.commit()
            return row["response"]

        if row:
            self.conn.execute("DELETE FROM cache_store WHERE cache_key = ?", (key,))
            self.conn.commit()

        return None

    def cache_set(
        self, prompt: str, model: str, response: str, tokens_used: int
    ) -> None:
        """Store a response in the cache."""
        key = self._cache_key(prompt, model)
        now = time.time()
        ttl = self.config.cache_ttl_hours * 3600

        self.conn.execute(
            """
            INSERT OR REPLACE INTO cache_store (cache_key, response, model, tokens_used, created_at, expires_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (key, response, model, tokens_used, now, now + ttl),
        )
        self.conn.commit()

    def check_budget(self) -> Tuple[bool, str]:
        """Check if we're within budget limits.

        Returns:
            (within_budget, reason)
        """
        today_start = self._today_start()

        row = self.conn.execute(
            """
            SELECT
                COALESCE(SUM(input_tokens + output_tokens), 0) as total_tokens,
                COALESCE(SUM(cost_usd), 0) as total_cost
            FROM usage_log
            WHERE timestamp >= ?
            """,
            (today_start,),
        ).fetchone()

        if row["total_tokens"] >= self.config.daily_token_limit:
            return False, f"Daily token limit reached: {row['total_tokens']:,}/{self.config.daily_token_limit:,}"

        if row["total_cost"] >= self.config.daily_cost_limit:
            return False, f"Daily cost limit reached: ${row['total_cost']:.2f}/${self.config.daily_cost_limit:.2f}"

        if self._session_cost >= self.config.session_cost_ceiling:
            return False, f"Session cost ceiling reached: ${self._session_cost:.2f}/${self.config.session_cost_ceiling:.2f}"

        return True, ""

    def record_usage(
        self,
        model: str,
        input_tokens: int,
        output_tokens: int,
        cached: bool = False,
        cache_key: Optional[str] = None,
        session_id: Optional[str] = None,
    ) -> TokenUsage:
        """Record token usage and compute cost."""
        pricing = MODEL_PRICING.get(model, MODEL_PRICING[self.config.default_model])

        if cached:
            cost = 0.0
        else:
            cost = (
                (input_tokens / 1000.0) * pricing["input"]
                + (output_tokens / 1000.0) * pricing["output"]
            )

        self.conn.execute(
            """
            INSERT INTO usage_log (timestamp, model, input_tokens, output_tokens, cached, cost_usd, cache_key, session_id)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (time.time(), model, input_tokens, output_tokens, 1 if cached else 0, cost, cache_key, session_id),
        )
        self.conn.commit()

        self._session_cost += cost

        return TokenUsage(
            model=model,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cached=cached,
            cost_usd=cost,
        )

    def process(
        self,
        prompt: str,
        preferred_model: Optional[str] = None,
        session_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Full pipeline: budget check -> cache check -> route -> record.

        Returns:
            Dict with keys: cached, model, budget_ok, budget_reason, usage.
        """
        budget_ok, budget_reason = self.check_budget()
        if not budget_ok:
            return {
                "cached": False,
                "model": None,
                "budget_ok": False,
                "budget_reason": budget_reason,
                "usage": None,
            }

        model = self.route_model(prompt, preferred_model)

        cached_response = self.cache_get(prompt, model)
        if cached_response is not None:
            usage = self.record_usage(model, 0, 0, cached=True)
            return {
                "cached": True,
                "model": model,
                "budget_ok": True,
                "budget_reason": "",
                "usage": usage,
                "response": cached_response,
            }

        return {
            "cached": False,
            "model": model,
            "budget_ok": True,
            "budget_reason": "",
            "usage": None,
        }

    def _today_start(self) -> float:
        """Get the start of today (UTC)."""
        import datetime
        now = datetime.datetime.now(datetime.timezone.utc)
        start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        return start.timestamp()

    def stats(self, days: int = 1) -> Dict[str, Any]:
        """Get cost and usage statistics.

        Args:
            days: Number of days to look back.
        """
        since = time.time() - (days * 86400)

        row = self.conn.execute(
            """
            SELECT
                COALESCE(SUM(input_tokens), 0) as total_input,
                COALESCE(SUM(output_tokens), 0) as total_output,
                COALESCE(SUM(cost_usd), 0) as total_cost,
                COALESCE(SUM(CASE WHEN cached = 1 THEN cost_usd ELSE 0 END), 0) as cache_savings
            FROM usage_log
            WHERE timestamp >= ?
            """,
            (since,),
        ).fetchone()

        cached_count = self.conn.execute(
            "SELECT COUNT(*) as cnt FROM usage_log WHERE cached = 1 AND timestamp >= ?",
            (since,),
        ).fetchone()["cnt"]

        total_count = self.conn.execute(
            "SELECT COUNT(*) as cnt FROM usage_log WHERE timestamp >= ?",
            (since,),
        ).fetchone()["cnt"]

        by_model = self.conn.execute(
            """
            SELECT
                model,
                SUM(input_tokens + output_tokens) as tokens,
                SUM(cost_usd) as cost,
                COUNT(*) as calls
            FROM usage_log
            WHERE timestamp >= ?
            GROUP BY model
            """,
            (since,),
        ).fetchall()

        cache_entries = self.conn.execute(
            "SELECT COUNT(*) as cnt FROM cache_store WHERE expires_at > ?",
            (time.time(),),
        ).fetchone()["cnt"]

        return {
            "period_days": days,
            "total_input_tokens": row["total_input"],
            "total_output_tokens": row["total_output"],
            "total_tokens": row["total_input"] + row["total_output"],
            "total_cost_usd": row["total_cost"],
            "cache_savings_usd": row["cache_savings"],
            "cache_hit_rate": (cached_count / total_count * 100) if total_count > 0 else 0.0,
            "total_calls": total_count,
            "cached_calls": cached_count,
            "by_model": {
                r["model"]: {"tokens": r["tokens"], "cost": r["cost"], "calls": r["calls"]}
                for r in by_model
            },
            "active_cache_entries": cache_entries,
            "session_cost": self._session_cost,
        }

    def close(self) -> None:
        """Close the database connection."""
        self.conn.close()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()
