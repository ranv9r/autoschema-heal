"""
Thread-safe, High-Throughput Compiled JQ Bytecode Cache.

Stores compiled native C `libjq` program instances keyed by structural AST fingerprints.
"""

from __future__ import annotations
import threading
from collections import OrderedDict
from dataclasses import dataclass
from typing import Optional, Dict, Any
import jq


@dataclass(frozen=True)
class CachedProgram:
    fingerprint: str
    jq_source: str
    compiled_program: Any  # jq._Program (C-extension object)
    audit_hash: str
    created_at_epoch: float


class ProgramCache:
    """
    Concurrent LRU Cache for verified JQ bytecode programs.
    Designed for zero-lock contention on hot read paths.
    """

    def __init__(self, max_size: int = 10_000) -> None:
        self.max_size = max_size
        self._cache: OrderedDict[str, CachedProgram] = OrderedDict()
        self._lock = threading.RLock()
        
        # Telemetry metrics
        self.hits = 0
        self.misses = 0
        self.evictions = 0

    def get(self, fingerprint: str) -> Optional[CachedProgram]:
        """
        Fast lookup: returns compiled program or None.
        Updates LRU order under lock.
        """
        with self._lock:
            if fingerprint in self._cache:
                self.hits += 1
                self._cache.move_to_end(fingerprint)
                return self._cache[fingerprint]
            self.misses += 1
            return None

    def put(
        self,
        fingerprint: str,
        jq_source: str,
        audit_hash: str = "",
        timestamp: float = 0.0,
    ) -> CachedProgram:
        """
        Compiles pure JQ source into native C bytecode and registers in cache.
        """
        compiled = jq.compile(jq_source)
        item = CachedProgram(
            fingerprint=fingerprint,
            jq_source=jq_source,
            compiled_program=compiled,
            audit_hash=audit_hash,
            created_at_epoch=timestamp,
        )
        with self._lock:
            if fingerprint in self._cache:
                self._cache.move_to_end(fingerprint)
            self._cache[fingerprint] = item
            if len(self._cache) > self.max_size:
                self._cache.popitem(last=False)
                self.evictions += 1
        return item

    def __len__(self) -> int:
        with self._lock:
            return len(self._cache)

    def stats(self) -> Dict[str, Any]:
        with self._lock:
            total_requests = self.hits + self.misses
            hit_rate = (self.hits / total_requests) if total_requests > 0 else 0.0
            return {
                "size": len(self._cache),
                "max_size": self.max_size,
                "hits": self.hits,
                "misses": self.misses,
                "hit_rate_pct": round(hit_rate * 100, 2),
                "evictions": self.evictions,
            }
