"""Local CLI agent-run session state."""

from __future__ import annotations

import json
import os
from pathlib import Path

DEFAULT_AGENT_SESSION_PATH = Path.home() / ".workrecorder" / "agent_session.json"


class AgentSessionStore:
    """Persist the active local CLI agent run id."""

    def __init__(self, path: Path = DEFAULT_AGENT_SESSION_PATH) -> None:
        self.path = path

    def resolve(self, explicit: str | None = None) -> str | None:
        """Resolve explicit/env/session run id in precedence order.

        Args:
            explicit: Run id provided by a CLI flag.

        Returns:
            The first available run id, or None when no local session exists.
        """

        if explicit:
            return explicit
        env_value = os.environ.get("WORKRECORDER_AGENT_RUN_ID")
        if env_value:
            return env_value
        return self.current()

    def current(self) -> str | None:
        """Return the stored active run id.

        Returns:
            The saved run id, or None when the session file is missing or invalid.
        """

        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
        except (FileNotFoundError, json.JSONDecodeError, OSError):
            return None
        value = payload.get("agent_run_id")
        return value if isinstance(value, str) and value else None

    def remember_from_payload(self, payload: dict[str, object]) -> None:
        """Persist a run id found in a daemon response envelope.

        Args:
            payload: Daemon response envelope that may contain an agent run id.
        """

        value = payload.get("agent_run_id")
        if not isinstance(value, str) or not value:
            data = payload.get("data")
            if isinstance(data, dict):
                nested = data.get("agent_run_id")
                value = nested if isinstance(nested, str) else value
        if not isinstance(value, str) or not value:
            return
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps({"agent_run_id": value}, ensure_ascii=False), encoding="utf-8")
