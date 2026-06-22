"""Read-only target admission checks for worker-ready repo promotion."""

from __future__ import annotations

import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from .config import ControllerConfig, RepoConfig
from .repo_health import RepoHealthReport, ScorecardClient
from .workflow_preflight import (
    WorkflowPreflightReport,
    build_workflow_preflight_report,
)


CommandRunner = Callable[[list[str], Path], subprocess.CompletedProcess[str]]


@dataclass(frozen=True)
class TargetAdmissionReport:
    repo: str
    status: str
    promotion_blockers: list[str] = field(default_factory=list)
    review_notes: list[str] = field(default_factory=list)
    enabled: bool = False
    worker_enabled: bool = False
    local_path: str = ""
    checkout_exists: bool = False
    current_branch: str = ""
    default_branch: str = ""
    on_default_branch: bool = False
    instructions: list[str] = field(default_factory=list)
    proof_commands: list[str] = field(default_factory=list)
    workflow_preflight: dict | None = None
    repo_health: dict | None = None

    def to_dict(self) -> dict:
        return {
            "repo": self.repo,
            "status": self.status,
            "promotion_blockers": self.promotion_blockers,
            "review_notes": self.review_notes,
            "enabled": self.enabled,
            "worker_enabled": self.worker_enabled,
            "local_path": self.local_path,
            "checkout_exists": self.checkout_exists,
            "current_branch": self.current_branch,
            "default_branch": self.default_branch,
            "on_default_branch": self.on_default_branch,
            "instructions": self.instructions,
            "proof_commands": self.proof_commands,
            "workflow_preflight": self.workflow_preflight,
            "repo_health": self.repo_health,
        }


def build_target_admission_report(
    config: ControllerConfig,
    repo_name: str,
    *,
    scorecard_client: ScorecardClient | None = None,
    workflow_tool: str = "wrkflw",
    command_runner: CommandRunner | None = None,
) -> TargetAdmissionReport:
    repo = _repo_config(config, repo_name)
    if repo is None:
        return TargetAdmissionReport(
            repo=repo_name,
            status="repo_not_configured",
            promotion_blockers=["repo_not_configured"],
        )

    repo_path = config.workspace / repo.local_path
    checkout_exists = repo_path.is_dir()
    current_branch = ""
    on_default_branch = False
    instructions: list[str] = []
    promotion_blockers: list[str] = []
    review_notes: list[str] = []

    if not repo.enabled:
        promotion_blockers.append("repo_disabled")
    if not repo.worker_enabled:
        promotion_blockers.append("worker_disabled")
    if not checkout_exists:
        promotion_blockers.append("repo_checkout_missing")
    else:
        current_branch = _current_branch(repo_path, command_runner or _run_command)
        on_default_branch = current_branch == repo.default_branch
        if current_branch and not on_default_branch:
            promotion_blockers.append("checkout_not_on_default_branch")
        instructions = _instruction_files(repo_path)
        if not instructions:
            review_notes.append("repo_instructions_missing")

    if not repo.proof_commands:
        promotion_blockers.append("proof_commands_missing")

    workflow_report = build_workflow_preflight_report(
        config,
        repo.name,
        executable=workflow_tool,
    )
    if workflow_report.status in {"repo_not_configured", "repo_checkout_missing"}:
        promotion_blockers.append(workflow_report.status)
    elif workflow_report.status in {"tool_missing", "no_workflows", "fail"}:
        review_notes.append(f"workflow_preflight_{workflow_report.status}")

    health_report = _repo_health(scorecard_client or ScorecardClient(), repo.name)
    if health_report.status == "error":
        review_notes.append("repo_health_error")
    elif health_report.status == "downgrade":
        review_notes.extend(
            f"repo_health_{reason}" for reason in health_report.advisory_reasons
        )

    status = "worker_ready" if not promotion_blockers else "blocked"
    if promotion_blockers == ["worker_disabled"]:
        status = "review_only"

    return TargetAdmissionReport(
        repo=repo.name,
        status=status,
        promotion_blockers=promotion_blockers,
        review_notes=review_notes,
        enabled=repo.enabled,
        worker_enabled=repo.worker_enabled,
        local_path=str(repo_path),
        checkout_exists=checkout_exists,
        current_branch=current_branch,
        default_branch=repo.default_branch,
        on_default_branch=on_default_branch,
        instructions=instructions,
        proof_commands=repo.proof_commands,
        workflow_preflight=workflow_report.to_dict(),
        repo_health=health_report.to_dict(),
    )


def _repo_config(config: ControllerConfig, repo_name: str) -> RepoConfig | None:
    for repo in config.repos:
        if repo.name == repo_name:
            return repo
    return None


def _repo_health(client: ScorecardClient, repo_name: str) -> RepoHealthReport:
    try:
        return client.repo_health(repo_name)
    except Exception:
        return RepoHealthReport(
            repo=repo_name,
            status="error",
            source_url=f"https://api.scorecard.dev/projects/github.com/{repo_name}",
            advisory_reasons=["repo_health_lookup_failed"],
            error="repo health lookup failed",
        )


def _current_branch(repo_path: Path, runner: CommandRunner) -> str:
    command = ["git", "rev-parse", "--abbrev-ref", "HEAD"]
    completed = runner(command, repo_path)
    if completed.returncode != 0:
        return ""
    return completed.stdout.strip()


def _instruction_files(repo_path: Path) -> list[str]:
    ignored_dirs = {".git", ".venv", "node_modules", "dist", "build", ".ruff_cache"}
    found: list[str] = []
    for directory in sorted(repo_path.iterdir(), key=lambda path: path.name):
        if directory.name in ignored_dirs:
            continue
        if directory.is_file() and directory.name == "AGENTS.md":
            found.append(directory.name)
        elif directory.is_dir():
            candidate = directory / "AGENTS.md"
            if candidate.exists():
                found.append(str(candidate.relative_to(repo_path)))
        if len(found) >= 10:
            break
    root_agents = repo_path / "AGENTS.md"
    if root_agents.exists() and "AGENTS.md" not in found:
        found.insert(0, "AGENTS.md")
    return found[:10]


def _run_command(
    command: list[str],
    cwd: Path,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        command,
        cwd=cwd,
        capture_output=True,
        text=True,
        timeout=10,
    )
