"""Review-only workflow preflight helpers."""

from __future__ import annotations

import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from .config import ControllerConfig, RepoConfig


PreflightRunner = Callable[[list[str], Path], subprocess.CompletedProcess[str]]


@dataclass(frozen=True)
class WorkflowPreflightReport:
    repo: str
    status: str
    local_path: str
    workflow_count: int
    command: list[str]
    exit_code: int | None = None
    stdout: str = ""
    stderr: str = ""
    error: str = ""

    def to_dict(self) -> dict:
        return {
            "repo": self.repo,
            "status": self.status,
            "local_path": self.local_path,
            "workflow_count": self.workflow_count,
            "command": self.command,
            "exit_code": self.exit_code,
            "stdout": self.stdout,
            "stderr": self.stderr,
            "error": self.error,
        }


def build_workflow_preflight_report(
    config: ControllerConfig,
    repo_name: str,
    *,
    executable: str = "wrkflw",
    runner: PreflightRunner | None = None,
) -> WorkflowPreflightReport:
    repo = _repo_config(config, repo_name)
    if repo is None:
        return WorkflowPreflightReport(
            repo=repo_name,
            status="repo_not_configured",
            local_path="",
            workflow_count=0,
            command=[],
            error=f"Repo not configured: {repo_name}",
        )

    repo_path = config.workspace / repo.local_path
    if not repo_path.exists():
        return WorkflowPreflightReport(
            repo=repo_name,
            status="repo_checkout_missing",
            local_path=str(repo_path),
            workflow_count=0,
            command=[],
            error=f"Repo checkout missing: {repo_path}",
        )

    workflows_dir = repo_path / ".github/workflows"
    workflow_files = workflow_paths(workflows_dir)
    if not workflow_files:
        return WorkflowPreflightReport(
            repo=repo_name,
            status="no_workflows",
            local_path=str(repo_path),
            workflow_count=0,
            command=[],
            error=f"No workflow files under {workflows_dir}",
        )

    tool_path = shutil.which(executable)
    command = [executable, "validate", ".github/workflows"]
    if tool_path is None:
        return WorkflowPreflightReport(
            repo=repo_name,
            status="tool_missing",
            local_path=str(repo_path),
            workflow_count=len(workflow_files),
            command=command,
            error=f"{executable} not found on PATH",
        )

    run = runner or run_preflight_command
    completed = run(command, repo_path)
    return WorkflowPreflightReport(
        repo=repo_name,
        status="pass" if completed.returncode == 0 else "fail",
        local_path=str(repo_path),
        workflow_count=len(workflow_files),
        command=command,
        exit_code=completed.returncode,
        stdout=completed.stdout,
        stderr=completed.stderr,
    )


def workflow_paths(workflows_dir: Path) -> list[Path]:
    if not workflows_dir.exists():
        return []
    paths = [
        path
        for pattern in ("*.yml", "*.yaml")
        for path in workflows_dir.glob(pattern)
        if path.is_file()
    ]
    return sorted(paths)


def run_preflight_command(
    command: list[str],
    cwd: Path,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        command,
        cwd=cwd,
        capture_output=True,
        text=True,
        check=False,
    )


def _repo_config(config: ControllerConfig, repo_name: str) -> RepoConfig | None:
    normalized = repo_name.lower()
    for repo in config.repos:
        if repo.name.lower() == normalized:
            return repo
    return None
