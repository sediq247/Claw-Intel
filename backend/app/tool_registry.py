"""Central, role-scoped registry for deterministic market-intelligence tools."""
import asyncio
import hashlib
import json
import time
from dataclasses import dataclass
from typing import Any, Awaitable, Callable, Type

from pydantic import BaseModel, ValidationError


class ToolAccessDenied(PermissionError):
    pass


class ToolExecutionFailed(RuntimeError):
    pass


@dataclass(frozen=True)
class ToolDefinition:
    name: str
    description: str
    provider: str
    operation: str
    allowed_agents: frozenset[str]
    required_permissions: frozenset[str]
    input_schema: Type[BaseModel]
    output_schema: Type[BaseModel]
    handler: Callable[[BaseModel], Awaitable[BaseModel | dict[str, Any]]]
    timeout_seconds: float = 3.0
    cache_seconds: int = 30
    cost_class: str = "internal"
    rate_limit: str = "bounded by the calling workflow"
    freshness_seconds: int | None = None


class ToolRegistry:
    def __init__(self):
        self._tools: dict[str, ToolDefinition] = {}
        self._cache: dict[tuple[str, str], tuple[float, dict[str, Any]]] = {}
        self._stats: dict[str, dict[str, int | float]] = {}

    def register(self, definition: ToolDefinition) -> None:
        if definition.name in self._tools:
            raise ValueError(f"Tool already registered: {definition.name}")
        if not definition.allowed_agents or definition.timeout_seconds <= 0:
            raise ValueError("Tools require explicit agent permissions and a positive timeout")
        self._tools[definition.name] = definition
        self._stats[definition.name] = {"calls": 0, "failures": 0, "cache_hits": 0, "elapsed_ms": 0.0}

    def catalog(self, agent_id: str | None = None) -> list[dict[str, Any]]:
        return [{
            "name": item.name, "description": item.description, "provider": item.provider,
            "operation": item.operation, "allowed_agents": sorted(item.allowed_agents),
            "required_permissions": sorted(item.required_permissions), "cost_class": item.cost_class,
            "rate_limit": item.rate_limit, "freshness_seconds": item.freshness_seconds,
            "timeout_seconds": item.timeout_seconds,
            "input_schema": item.input_schema.model_json_schema(),
            "output_schema": item.output_schema.model_json_schema(),
        } for item in self._tools.values() if agent_id is None or agent_id in item.allowed_agents]

    def stats(self) -> dict[str, dict[str, int | float]]:
        return {key: dict(value) for key, value in self._stats.items()}

    async def execute(self, name: str, agent_id: str, arguments: dict[str, Any],
                      permissions: set[str] | frozenset[str] = frozenset()) -> dict[str, Any]:
        definition = self._tools.get(name)
        if definition is None:
            raise ToolAccessDenied("Tool is not registered")
        if agent_id not in definition.allowed_agents or not definition.required_permissions.issubset(permissions):
            raise ToolAccessDenied("Agent is not authorised to use this tool")
        if not isinstance(arguments, dict):
            raise ToolExecutionFailed("Tool input must be an object")
        try:
            parsed = definition.input_schema.model_validate(arguments)
        except ValidationError as exc:
            raise ToolExecutionFailed("Tool input failed schema validation") from exc
        canonical = json.dumps(parsed.model_dump(mode="json"), sort_keys=True, separators=(",", ":"))
        cache_key = (name, hashlib.sha256(canonical.encode("utf-8")).hexdigest())
        cached = self._cache.get(cache_key)
        if cached and cached[0] > time.monotonic():
            self._stats[name]["cache_hits"] += 1
            return dict(cached[1])

        started = time.perf_counter()
        self._stats[name]["calls"] += 1
        try:
            result = await asyncio.wait_for(definition.handler(parsed), timeout=definition.timeout_seconds)
            validated = definition.output_schema.model_validate(result)
            output = validated.model_dump(mode="json")
        except (TimeoutError, ValidationError, ValueError, TypeError) as exc:
            self._stats[name]["failures"] += 1
            raise ToolExecutionFailed("Tool failed or returned invalid output") from exc
        except Exception as exc:
            self._stats[name]["failures"] += 1
            raise ToolExecutionFailed("Tool execution failed") from exc
        finally:
            self._stats[name]["elapsed_ms"] += (time.perf_counter() - started) * 1000
        if definition.cache_seconds:
            self._cache[cache_key] = (time.monotonic() + definition.cache_seconds, output)
            if len(self._cache) > 2048:
                now = time.monotonic()
                self._cache = {key: value for key, value in self._cache.items() if value[0] > now}
                if len(self._cache) > 2048:
                    self._cache = dict(list(self._cache.items())[-1024:])
        return output
