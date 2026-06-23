from __future__ import annotations

import fnmatch
from collections import defaultdict
from typing import Any


class InMemoryPipeline:
    def __init__(self, redis: "InMemoryRedis"):
        self.redis = redis
        self.ops: list[tuple[str, tuple[Any, ...]]] = []

    def incr(self, key: str, amount: int = 1):
        self.ops.append(("incr", (key, amount)))
        return self

    def expire(self, key: str, seconds: int):
        self.ops.append(("expire", (key, seconds)))
        return self

    async def execute(self) -> list[Any]:
        results = []
        for name, args in self.ops:
            if name == "incr":
                results.append(await self.redis.incr(*args))
            elif name == "expire":
                results.append(await self.redis.expire(*args))
        self.ops.clear()
        return results


class InMemoryRedis:
    """Minimal async Redis double for unit and service-logic tests."""

    def __init__(self):
        self._hashes: dict[str, dict[str, Any]] = defaultdict(dict)
        self._sorted_sets: dict[str, dict[str, float]] = defaultdict(dict)
        self._lists: dict[str, list[Any]] = defaultdict(list)
        self._strings: dict[str, Any] = {}

    def pipeline(self) -> InMemoryPipeline:
        return InMemoryPipeline(self)

    async def close(self):
        return None

    async def zadd(self, key: str, mapping: dict[str, float]):
        self._sorted_sets[key].update(mapping)

    async def zpopmin(self, key: str, count: int = 1):
        items = sorted(self._sorted_sets[key].items(), key=lambda item: (item[1], item[0]))
        popped = items[:count]
        for member, _ in popped:
            del self._sorted_sets[key][member]
        return popped

    async def zcard(self, key: str) -> int:
        return len(self._sorted_sets[key])

    async def hset(
        self,
        key: str,
        field: str | None = None,
        value: Any | None = None,
        mapping: dict[str, Any] | None = None,
    ):
        if mapping is not None:
            self._hashes[key].update(mapping)
        elif field is not None:
            self._hashes[key][field] = value
        else:
            raise TypeError("hset requires mapping or field/value")

    async def hgetall(self, key: str) -> dict[str, Any]:
        return dict(self._hashes.get(key, {}))

    async def hincrby(self, key: str, field: str, amount: int):
        current = int(self._hashes[key].get(field, 0))
        self._hashes[key][field] = current + amount
        return self._hashes[key][field]

    async def keys(self, pattern: str) -> list[str]:
        all_keys = set(self._hashes) | set(self._sorted_sets) | set(self._lists) | set(self._strings)
        return sorted(key for key in all_keys if fnmatch.fnmatch(key, pattern))

    async def delete(self, key: str):
        self._hashes.pop(key, None)
        self._sorted_sets.pop(key, None)
        self._lists.pop(key, None)
        self._strings.pop(key, None)

    async def lpush(self, key: str, value: Any):
        self._lists[key].insert(0, value)

    async def ltrim(self, key: str, start: int, end: int):
        values = self._lists[key]
        if end == -1:
            end = len(values) - 1
        self._lists[key] = values[start:end + 1]

    async def lrange(self, key: str, start: int, end: int) -> list[Any]:
        values = self._lists.get(key, [])
        if end == -1:
            end = len(values) - 1
        return values[start:end + 1]

    async def get(self, key: str):
        return self._strings.get(key)

    async def incr(self, key: str, amount: int = 1):
        self._strings[key] = int(self._strings.get(key, 0)) + amount
        return self._strings[key]

    async def expire(self, key: str, seconds: int):
        return True