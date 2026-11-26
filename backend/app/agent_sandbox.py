"""Short-lived, agent-scoped scratch workspaces for backend orchestration.

These workspaces are private to one agent call, accept only bounded JSON/text
artifacts, expose no shell or code execution, and are removed when the call ends.
"""
import json
import re
import tempfile
from pathlib import Path
from typing import Any


_SAFE_NAME = re.compile(r"^[a-z][a-z0-9_-]{0,31}$")
_MAX_ARTIFACT_BYTES = 128_000


class AgentWorkspace:
    def __init__(self, root: Path, agent_id: str):
        if not _SAFE_NAME.fullmatch(agent_id):
            raise ValueError("Invalid agent workspace identity")
        self.root = root.resolve()
        self.agent_id = agent_id
        self.path = (self.root / agent_id).resolve()
        if self.root not in self.path.parents:
            raise ValueError("Agent workspace escaped its sandbox")
        self.path.mkdir(parents=True, exist_ok=True)

    def write_json(self, name: str, value: Any) -> Path:
        if not _SAFE_NAME.fullmatch(name):
            raise ValueError("Invalid sandbox artifact name")
        target = (self.path / f"{name}.json").resolve()
        if self.path not in target.parents:
            raise ValueError("Sandbox artifact escaped its workspace")
        content = json.dumps(value, ensure_ascii=False, default=str)
        if len(content.encode("utf-8")) > _MAX_ARTIFACT_BYTES:
            raise ValueError("Sandbox artifact exceeds the configured size limit")
        target.write_text(content, encoding="utf-8")
        return target


class AgentSandbox:
    """Create isolated per-agent directories that are deleted on exit."""

    def __init__(self):
        self._temporary = tempfile.TemporaryDirectory(prefix="zecto-agent-work-")
        self.root = Path(self._temporary.name).resolve()

    def workspace(self, agent_id: str) -> AgentWorkspace:
        return AgentWorkspace(self.root, agent_id)

    def close(self) -> None:
        self._temporary.cleanup()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback):
        self.close()
