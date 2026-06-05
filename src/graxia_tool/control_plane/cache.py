"""Tool-Call Cache — TTL, LRU eviction, semantic similarity matching via SQLite."""

from __future__ import annotations

import collections
import hashlib
import json
import math
import os
import sqlite3
import struct
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _hash_key(tool_name: str, args: Dict[str, Any]) -> str:
    """Deterministic hash of tool name + serialised args."""
    blob = json.dumps({"tool": tool_name, "args": args}, sort_keys=True, default=str)
    return hashlib.sha256(blob.encode()).hexdigest()


def _cosine_sim(a: List[float], b: List[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(x * x for x in b))
    if na == 0 or nb == 0:
        return 0.0
    return dot / (na * nb)


def _embed_text(text: str, dim: int = 128) -> List[float]:
    """Deterministic bag-of-words embedding (no external deps)."""
    vec = [0.0] * dim
    for token in text.lower().split():
        h = int.from_bytes(hashlib.md5(token.encode()).digest()[:4], "big")
        idx = h % dim
        sign = 1.0 if (h // dim) % 2 == 0 else -1.0
        vec[idx] += sign
    # L2-normalise
    norm = math.sqrt(sum(x * x for x in vec))
    if norm:
        vec = [x / norm for x in vec]
    return vec


def _embed_bytes(vec: List[float]) -> bytes:
    return struct.pack(f"{len(vec)}f", *vec)


def _devec_bytes(data: bytes, dim: int = 128) -> List[float]:
    return list(struct.unpack(f"{dim}f", data[:dim * 4]))


# ---------------------------------------------------------------------------
# TTL presets
# ---------------------------------------------------------------------------

class CacheTTL:
    DYNAMIC = 3600        # 1 hour
    STATIC = 86400        # 24 hours
    IMMEDIATE = 0         # never cache
    CUSTOM = -1           # caller-supplied


# ---------------------------------------------------------------------------
# ToolCache
# ---------------------------------------------------------------------------

class ToolCache:
    """SQLite-backed tool result cache with LRU eviction + semantic matching."""

    def __init__(
        self,
        db_path: str | Path = ".graxia_cache.db",
        max_entries: int = 1000,
        similarity_threshold: float = 0.85,
    ) -> None:
        self._db_path = str(db_path)
        self._max = max_entries
        self._sim_thresh = similarity_threshold
        self._conn = sqlite3.connect(self._db_path)
        self._conn.row_factory = sqlite3.Row
        self._ensure_schema()
        self._access_order: collections.OrderedDict[str, None] = collections.OrderedDict()
        self._load_lru()

    # ---- schema -----------------------------------------------------------

    def _ensure_schema(self) -> None:
        self._conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS cache (
                key          TEXT PRIMARY KEY,
                tool_name    TEXT NOT NULL,
                args_json    TEXT DEFAULT '{}',
                result_json  TEXT DEFAULT 'null',
                embedding    BLOB,
                ttl          INTEGER NOT NULL DEFAULT 3600,
                created_at   REAL NOT NULL,
                expires_at   REAL NOT NULL,
                hit_count    INTEGER NOT NULL DEFAULT 0,
                last_hit     REAL DEFAULT 0
            );
            CREATE INDEX IF NOT EXISTS idx_cache_tool ON cache(tool_name);
            CREATE INDEX IF NOT EXISTS idx_cache_expires ON cache(expires_at);

            CREATE TABLE IF NOT EXISTS cache_log (
                id     INTEGER PRIMARY KEY AUTOINCREMENT,
                key    TEXT NOT NULL,
                action TEXT NOT NULL,
                ts     REAL NOT NULL
            );
            """
        )
        self._conn.commit()

    def _load_lru(self) -> None:
        rows = self._conn.execute(
            "SELECT key FROM cache ORDER BY last_hit DESC, created_at DESC LIMIT ?",
            (self._max,),
        ).fetchall()
        for r in rows:
            self._access_order[r["key"]] = None

    # ---- internal helpers -------------------------------------------------

    def _now(self) -> float:
        return time.time()

    def _evict_expired(self) -> int:
        now = self._now()
        cur = self._conn.execute("DELETE FROM cache WHERE expires_at < ?", (now,))
        self._conn.commit()
        return cur.rowcount

    def _evict_lru(self, count: int = 1) -> None:
        for _ in range(count):
            if not self._access_order:
                break
            key, _ = self._access_order.popitem(last=False)
            self._conn.execute("DELETE FROM cache WHERE key=?", (key,))
        self._conn.commit()

    def _touch(self, key: str) -> None:
        self._access_order.move_to_end(key, last=True)

    def _record_log(self, key: str, action: str) -> None:
        self._conn.execute(
            "INSERT INTO cache_log (key,action,ts) VALUES (?,?,?)",
            (key, action, self._now()),
        )

    # ---- public API -------------------------------------------------------

    def get(self, tool_name: str, args: Dict[str, Any]) -> Any | None:
        """Exact-match lookup. Returns cached result or None."""
        key = _hash_key(tool_name, args)
        row = self._conn.execute("SELECT * FROM cache WHERE key=?", (key,)).fetchone()
        if not row:
            return None
        if row["expires_at"] < self._now():
            self.invalidate_key(key)
            return None
        # update hit stats
        self._conn.execute(
            "UPDATE cache SET hit_count=hit_count+1, last_hit=? WHERE key=?",
            (self._now(), key),
        )
        self._conn.commit()
        self._touch(key)
        return json.loads(row["result_json"])

    def get_semantic(
        self, tool_name: str, args: Dict[str, Any]
    ) -> Tuple[Any | None, float]:
        """Semantic lookup: finds nearest cached result by cosine similarity."""
        query_emb = _embed_text(json.dumps(args, sort_keys=True, default=str))
        best_score = 0.0
        best_result: Any | None = None
        best_key: str | None = None

        for row in self._conn.execute(
            "SELECT key, embedding, result_json, expires_at FROM cache WHERE tool_name=?",
            (tool_name,),
        ):
            if row["expires_at"] < self._now():
                continue
            if not row["embedding"]:
                continue
            emb = _devec_bytes(row["embedding"])
            score = _cosine_sim(query_emb, emb)
            if score > best_score:
                best_score = score
                best_result = json.loads(row["result_json"])
                best_key = row["key"]

        if best_score >= self._sim_thresh and best_key:
            self._conn.execute(
                "UPDATE cache SET hit_count=hit_count+1, last_hit=? WHERE key=?",
                (self._now(), best_key),
            )
            self._conn.commit()
            self._touch(best_key)
            return best_result, best_score

        return None, 0.0

    def set(
        self,
        tool_name: str,
        args: Dict[str, Any],
        result: Any,
        ttl: int = CacheTTL.DYNAMIC,
        semantic: bool = True,
    ) -> str:
        """Store result. Returns cache key."""
        if ttl == CacheTTL.IMMEDIATE:
            return ""
        if ttl == CacheTTL.CUSTOM:
            ttl = CacheTTL.DYNAMIC

        key = _hash_key(tool_name, args)
        now = self._now()
        expires = now + ttl

        emb = None
        if semantic:
            emb = _embed_bytes(
                _embed_text(json.dumps(args, sort_keys=True, default=str))
            )

        # evict if over capacity
        total = self._conn.execute("SELECT COUNT(*) as n FROM cache").fetchone()["n"]
        if total >= self._max:
            self._evict_lru(count=max(1, total - self._max + 1))

        self._conn.execute(
            """INSERT OR REPLACE INTO cache
               (key,tool_name,args_json,result_json,embedding,ttl,created_at,expires_at,hit_count,last_hit)
               VALUES (?,?,?,?,?,?,?,?,0,0)""",
            (key, tool_name, json.dumps(args, default=str), json.dumps(result, default=str),
             emb, ttl, now, expires),
        )
        self._conn.commit()
        self._access_order[key] = None
        self._record_log(key, "set")
        return key

    # ---- invalidation -----------------------------------------------------

    def invalidate_key(self, key: str) -> bool:
        cur = self._conn.execute("DELETE FROM cache WHERE key=?", (key,))
        self._conn.commit()
        if cur.rowcount:
            self._access_order.pop(key, None)
            self._record_log(key, "invalidate_key")
            return True
        return False

    def invalidate_pattern(self, tool_name: str | None = None, pattern: str = "") -> int:
        """Invalidate entries matching tool_name and/or glob-like pattern in key."""
        sql = "DELETE FROM cache WHERE 1=1"
        params: list = []
        if tool_name:
            sql += " AND tool_name=?"
            params.append(tool_name)
        if pattern:
            sql += " AND key LIKE ?"
            params.append(pattern.replace("*", "%"))
        cur = self._conn.execute(sql, params)
        self._conn.commit()
        # rebuild LRU
        self._access_order.clear()
        self._load_lru()
        self._record_log("*", f"invalidate_pattern:{tool_name}:{pattern}")
        return cur.rowcount

    def invalidate_expired(self) -> int:
        count = self._evict_expired()
        self._access_order.clear()
        self._load_lru()
        self._record_log("*", "invalidate_expired")
        return count

    # ---- stats & maintenance ----------------------------------------------

    def stats(self) -> Dict[str, Any]:
        total = self._conn.execute("SELECT COUNT(*) as n FROM cache").fetchone()["n"]
        hits = self._conn.execute("SELECT SUM(hit_count) as h FROM cache").fetchone()["h"] or 0
        expired = self._conn.execute(
            "SELECT COUNT(*) as n FROM cache WHERE expires_at < ?", (self._now(),)
        ).fetchone()["n"]
        by_tool = {}
        for row in self._conn.execute(
            "SELECT tool_name, COUNT(*) as n, SUM(hit_count) as h FROM cache GROUP BY tool_name"
        ):
            by_tool[row["tool_name"]] = {"entries": row["n"], "hits": row["h"] or 0}
        return {
            "total_entries": total,
            "total_hits": hits,
            "expired_pending": expired,
            "max_entries": self._max,
            "by_tool": by_tool,
            "lru_size": len(self._access_order),
        }

    def clear(self) -> int:
        cur = self._conn.execute("DELETE FROM cache")
        self._conn.commit()
        self._access_order.clear()
        self._record_log("*", "clear")
        return cur.rowcount

    def close(self) -> None:
        self._conn.close()
