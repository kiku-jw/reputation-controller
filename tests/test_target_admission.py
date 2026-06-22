import subprocess
from pathlib import Path

from reputation_controller.config import ControllerConfig, RepoConfig
from reputation_controller.repo_health import RepoHealthReport
from reputation_controller.target_admission import build_target_admission_report


class FakeScorecardClient:
    def repo_health(self, repo: str):
        return RepoHealthReport(
            repo=repo,
            status="downgrade",
            source_url=f"https://api.scorecard.dev/projects/github.com/{repo}",
            advisory_reasons=["weak_branch_protection"],
        )


def fake_runner(command, cwd):
    return subprocess.CompletedProcess(
        command,
        0,
        stdout="feature-branch\n",
        stderr="",
    )


def make_config(tmp_path: Path) -> ControllerConfig:
    return ControllerConfig(
        workspace=tmp_path,
        state_dir=".controller/state",
        dry_run=True,
        repos=[
            RepoConfig(
                name="acme/widgets",
                local_path="widgets",
                default_branch="main",
                enabled=True,
                worker_enabled=False,
                proof_commands=["python3 -m pytest tests/test_widgets.py -q"],
            )
        ],
    )


def test_target_admission_reports_review_only_checkout_state(tmp_path: Path):
    repo_path = tmp_path / "widgets"
    repo_path.mkdir()
    (repo_path / "AGENTS.md").write_text("instructions")
    workflows_dir = repo_path / ".github/workflows"
    workflows_dir.mkdir(parents=True)
    (workflows_dir / "ci.yml").write_text("name: ci\n")

    report = build_target_admission_report(
        make_config(tmp_path),
        "acme/widgets",
        scorecard_client=FakeScorecardClient(),
        workflow_tool="__missing_wrkflw__",
        command_runner=fake_runner,
    )

    data = report.to_dict()
    assert data["status"] == "blocked"
    assert data["promotion_blockers"] == [
        "worker_disabled",
        "checkout_not_on_default_branch",
    ]
    assert data["checkout_exists"] is True
    assert data["current_branch"] == "feature-branch"
    assert data["on_default_branch"] is False
    assert data["instructions"] == ["AGENTS.md"]
    assert data["proof_commands"] == ["python3 -m pytest tests/test_widgets.py -q"]
    assert "workflow_preflight_tool_missing" in data["review_notes"]
    assert "repo_health_weak_branch_protection" in data["review_notes"]


def test_target_admission_blocks_missing_proof_commands(tmp_path: Path):
    config = ControllerConfig(
        workspace=tmp_path,
        state_dir=".controller/state",
        dry_run=True,
        repos=[
            RepoConfig(
                name="acme/widgets",
                local_path="widgets",
                default_branch="main",
                enabled=True,
                worker_enabled=True,
            )
        ],
    )

    report = build_target_admission_report(
        config,
        "acme/widgets",
        scorecard_client=FakeScorecardClient(),
        workflow_tool="__missing_wrkflw__",
    )

    assert report.status == "blocked"
    assert "repo_checkout_missing" in report.promotion_blockers
    assert "proof_commands_missing" in report.promotion_blockers


def test_target_admission_unknown_repo_is_read_only(tmp_path: Path):
    report = build_target_admission_report(
        make_config(tmp_path),
        "acme/unknown",
        scorecard_client=FakeScorecardClient(),
    )

    assert report.status == "repo_not_configured"
    assert report.promotion_blockers == ["repo_not_configured"]
