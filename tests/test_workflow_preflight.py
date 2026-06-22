import json
import subprocess
from pathlib import Path

from reputation_controller.config import load_config
from reputation_controller.workflow_preflight import build_workflow_preflight_report


def write_config(tmp_path: Path) -> Path:
    config_path = tmp_path / "controller.json"
    config_path.write_text(
        json.dumps(
            {
                "workspace": str(tmp_path),
                "state_dir": ".controller/state",
                "dry_run": True,
                "repos": [
                    {
                        "name": "owner/repo",
                        "local_path": "repo",
                        "default_branch": "main",
                    }
                ],
            }
        )
    )
    return config_path


def make_workflow_repo(tmp_path: Path) -> None:
    workflows = tmp_path / "repo/.github/workflows"
    workflows.mkdir(parents=True)
    (workflows / "ci.yml").write_text("name: ci\non: push\njobs: {}\n")


def test_workflow_preflight_reports_missing_tool(tmp_path: Path, monkeypatch):
    make_workflow_repo(tmp_path)
    config = load_config(write_config(tmp_path))
    monkeypatch.setattr(
        "reputation_controller.workflow_preflight.shutil.which",
        lambda executable: None,
    )

    report = build_workflow_preflight_report(config, "owner/repo")

    assert report.status == "tool_missing"
    assert report.workflow_count == 1
    assert report.command == ["wrkflw", "validate", ".github/workflows"]
    assert "not found" in report.error


def test_workflow_preflight_reports_no_workflows(tmp_path: Path):
    (tmp_path / "repo").mkdir()
    config = load_config(write_config(tmp_path))

    report = build_workflow_preflight_report(config, "owner/repo")

    assert report.status == "no_workflows"
    assert report.workflow_count == 0


def test_workflow_preflight_runs_wrkflw_when_available(tmp_path: Path, monkeypatch):
    make_workflow_repo(tmp_path)
    config = load_config(write_config(tmp_path))
    monkeypatch.setattr(
        "reputation_controller.workflow_preflight.shutil.which",
        lambda executable: "/usr/local/bin/wrkflw",
    )
    calls = []

    def fake_runner(command, cwd):
        calls.append((command, cwd))
        return subprocess.CompletedProcess(
            args=command,
            returncode=0,
            stdout="valid",
            stderr="",
        )

    report = build_workflow_preflight_report(
        config,
        "owner/repo",
        runner=fake_runner,
    )

    assert report.status == "pass"
    assert report.exit_code == 0
    assert report.stdout == "valid"
    assert calls == [(["wrkflw", "validate", ".github/workflows"], tmp_path / "repo")]
