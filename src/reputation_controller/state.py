"""Persistent controller state."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class Sprint:
    sprint_id: str
    repo: str
    issue_number: int
    title: str
    status: str

    @classmethod
    def from_dict(cls, data: dict) -> "Sprint":
        return cls(
            sprint_id=data["sprint_id"],
            repo=data["repo"],
            issue_number=int(data["issue_number"]),
            title=data["title"],
            status=data["status"],
        )

    def to_dict(self) -> dict:
        return {
            "sprint_id": self.sprint_id,
            "repo": self.repo,
            "issue_number": self.issue_number,
            "title": self.title,
            "status": self.status,
        }


@dataclass
class ControllerState:
    active_sprints: list[Sprint] = field(default_factory=list)
    completed_sprints: list[Sprint] = field(default_factory=list)
    open_hypotheses: list[str] = field(default_factory=list)
    target_history: list[str] = field(default_factory=list)
    events: list[dict] = field(default_factory=list)

    @classmethod
    def from_dict(cls, data: dict) -> "ControllerState":
        return cls(
            active_sprints=[
                Sprint.from_dict(item) for item in data.get("active_sprints", [])
            ],
            completed_sprints=[
                Sprint.from_dict(item) for item in data.get("completed_sprints", [])
            ],
            open_hypotheses=list(data.get("open_hypotheses", [])),
            target_history=list(data.get("target_history", [])),
            events=list(data.get("events", [])),
        )

    def to_dict(self) -> dict:
        return {
            "active_sprints": [sprint.to_dict() for sprint in self.active_sprints],
            "completed_sprints": [
                sprint.to_dict() for sprint in self.completed_sprints
            ],
            "open_hypotheses": self.open_hypotheses,
            "target_history": self.target_history,
            "events": self.events,
        }


class StateStore:
    def __init__(self, path: Path):
        self.path = path

    def load(self) -> ControllerState:
        if not self.path.exists():
            return ControllerState()
        return ControllerState.from_dict(json.loads(self.path.read_text()))

    def save(self, state: ControllerState) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(state.to_dict(), indent=2, sort_keys=True))

    def resolve_sprint(self, sprint_id: str, status: str) -> bool:
        state = self.load()
        for index, sprint in enumerate(state.active_sprints):
            if sprint.sprint_id == sprint_id:
                resolved = Sprint(
                    sprint_id=sprint.sprint_id,
                    repo=sprint.repo,
                    issue_number=sprint.issue_number,
                    title=sprint.title,
                    status=status,
                )
                del state.active_sprints[index]
                state.completed_sprints.append(resolved)
                self.save(state)
                return True
        return False
