"""Worker command construction.

The controller prepares bounded worker commands, but does not execute them from
the decision loop in v0. This keeps unattended operation dry-run first.
"""

from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

from .public_actions import PublicActionProposal


@dataclass(frozen=True)
class WorkerSpec:
    repo_path: Path
    packet_path: Path
    evidence_dir: Path
    result_path: Path
    model: str = "gpt-5.4-mini"
    timeout_seconds: int = 1800


@dataclass(frozen=True)
class WorkerResult:
    verdict: str
    summary: str
    changed_files: list[str] = field(default_factory=list)
    verification: list[str] = field(default_factory=list)
    public_action_proposal: PublicActionProposal | None = None

    @classmethod
    def from_dict(cls, data: dict) -> "WorkerResult":
        proposal_raw = data.get("public_action_proposal")
        proposal = None
        if isinstance(proposal_raw, dict):
            proposal = PublicActionProposal.from_dict(proposal_raw)
        return cls(
            verdict=str(data.get("verdict", "")),
            summary=str(data.get("summary", "")),
            changed_files=[str(item) for item in data.get("changed_files", [])],
            verification=[str(item) for item in data.get("verification", [])],
            public_action_proposal=proposal,
        )

    @classmethod
    def from_file(cls, path: Path) -> "WorkerResult":
        return cls.from_dict(json.loads(path.read_text()))

    def to_dict(self) -> dict:
        return {
            "verdict": self.verdict,
            "summary": self.summary,
            "changed_files": self.changed_files,
            "verification": self.verification,
            "public_action_proposal": (
                self.public_action_proposal.to_dict()
                if self.public_action_proposal
                else None
            ),
        }


def build_worker_command(spec: WorkerSpec) -> list[str]:
    prompt = (
        "Read the sprint packet and repo instructions. Work locally only. "
        "Do not post public comments, create PRs, push branches, or force-push. "
        f"Store evidence under {spec.evidence_dir}. "
        f"Write exactly one JSON object to {spec.result_path} with keys: "
        "verdict, summary, changed_files, verification, public_action_proposal. "
        "verdict must be proof, kill, or needs-human. "
        "public_action_proposal may be null, or an object with action, repo, "
        "issue_number, body, title, branch, draft, evidence, verification. "
        f"Packet: {spec.packet_path}"
    )
    return [
        "codex",
        "exec",
        "-c",
        'service_tier="fast"',
        "--model",
        _codex_cli_model(spec.model),
        "--cd",
        str(spec.repo_path),
        "--add-dir",
        str(spec.evidence_dir),
        "--sandbox",
        "workspace-write",
        "--full-auto",
        prompt,
    ]


def run_worker(spec: WorkerSpec) -> subprocess.CompletedProcess[str]:
    spec.evidence_dir.mkdir(parents=True, exist_ok=True)
    command = build_worker_command(spec)
    return subprocess.run(
        command,
        check=False,
        capture_output=True,
        text=True,
        timeout=spec.timeout_seconds,
    )


def prepare_repo_checkout(
    repo_path: Path,
    *,
    default_branch: str,
) -> list[str]:
    commands = [
        ["git", "fetch", "upstream", default_branch, "--prune"],
        ["git", "checkout", default_branch],
        ["git", "reset", "--hard", f"upstream/{default_branch}"],
        ["git", "clean", "-fd"],
    ]
    output: list[str] = []
    for command in commands:
        completed = subprocess.run(
            command,
            cwd=repo_path,
            check=True,
            capture_output=True,
            text=True,
        )
        output.append("$ " + " ".join(command))
        if completed.stdout.strip():
            output.append(completed.stdout.strip())
        if completed.stderr.strip():
            output.append(completed.stderr.strip())
    return output


def _codex_cli_model(model: str) -> str:
    if model.startswith("codex/"):
        return model.removeprefix("codex/")
    if model.startswith("cx/"):
        return model.removeprefix("cx/")
    return model or "gpt-5.4-mini"
