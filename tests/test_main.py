import importlib
import json
import sys
from pathlib import Path


cli = importlib.import_module("reputation_controller.__main__")


class FakePlatformReport:
    def to_dict(self):
        return {
            "summary": {
                "admitted_count": 0,
                "rejected_count": 0,
                "worker_enabled_count": 0,
            },
            "platforms": [],
        }


class FakeRepoHealthReport:
    def to_dict(self):
        return {
            "repo": "owner/repo",
            "status": "pass",
            "source_url": "https://api.scorecard.dev/projects/github.com/owner/repo",
        }


class FakeScorecardClient:
    def repo_health(self, repo: str):
        return FakeRepoHealthReport()


class FakeWorkflowPreflightReport:
    def to_dict(self):
        return {
            "repo": "owner/repo",
            "status": "tool_missing",
            "workflow_count": 1,
        }


class FakeTargetAdmissionReport:
    def to_dict(self):
        return {
            "repo": "owner/repo",
            "status": "blocked",
            "promotion_blockers": ["proof_commands_missing"],
        }


def test_platform_scout_cli_does_not_create_state(tmp_path: Path, monkeypatch, capsys):
    config_path = tmp_path / "controller.json"
    config_path.write_text(
        json.dumps(
            {
                "workspace": str(tmp_path),
                "state_dir": ".controller/state",
                "dry_run": True,
                "repos": [],
                "paid_platforms": [
                    {
                        "name": "opire",
                        "provider": "opire",
                        "endpoint_url": "https://api.opire.dev/rewards",
                    }
                ],
            }
        )
    )
    calls = []

    def fake_build_paid_platform_report(config, github, limit):
        calls.append((config, github, limit))
        return FakePlatformReport()

    monkeypatch.setattr(
        sys,
        "argv",
        [
            "reputation-controller",
            "--config",
            str(config_path),
            "platform-scout",
            "--limit",
            "2",
        ],
    )
    monkeypatch.setattr(
        cli,
        "build_paid_platform_report",
        fake_build_paid_platform_report,
    )

    result = cli.main()

    assert result == 0
    assert calls[0][2] == 2
    assert not (tmp_path / ".controller/state/state.json").exists()
    assert '"worker_enabled_count": 0' in capsys.readouterr().out


def test_repo_health_cli_does_not_create_state(tmp_path: Path, monkeypatch, capsys):
    config_path = tmp_path / "controller.json"
    config_path.write_text(
        json.dumps(
            {
                "workspace": str(tmp_path),
                "state_dir": ".controller/state",
                "dry_run": True,
                "repos": [],
            }
        )
    )
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "reputation-controller",
            "--config",
            str(config_path),
            "repo-health",
            "--repo",
            "owner/repo",
        ],
    )
    monkeypatch.setattr(cli, "ScorecardClient", lambda: FakeScorecardClient())

    result = cli.main()

    assert result == 0
    assert not (tmp_path / ".controller/state/state.json").exists()
    assert '"status": "pass"' in capsys.readouterr().out


def test_workflow_preflight_cli_does_not_create_state(
    tmp_path: Path,
    monkeypatch,
    capsys,
):
    config_path = tmp_path / "controller.json"
    config_path.write_text(
        json.dumps(
            {
                "workspace": str(tmp_path),
                "state_dir": ".controller/state",
                "dry_run": True,
                "repos": [],
            }
        )
    )

    def fake_build_workflow_preflight_report(config, repo, executable):
        return FakeWorkflowPreflightReport()

    monkeypatch.setattr(
        sys,
        "argv",
        [
            "reputation-controller",
            "--config",
            str(config_path),
            "workflow-preflight",
            "--repo",
            "owner/repo",
        ],
    )
    monkeypatch.setattr(
        cli,
        "build_workflow_preflight_report",
        fake_build_workflow_preflight_report,
    )

    result = cli.main()

    assert result == 0
    assert not (tmp_path / ".controller/state/state.json").exists()
    assert '"status": "tool_missing"' in capsys.readouterr().out


def test_target_admission_cli_does_not_create_state(
    tmp_path: Path, monkeypatch, capsys
):
    config_path = tmp_path / "controller.json"
    config_path.write_text(
        json.dumps(
            {
                "workspace": str(tmp_path),
                "state_dir": ".controller/state",
                "dry_run": True,
                "repos": [],
            }
        )
    )

    def fake_build_target_admission_report(config, repo, workflow_tool):
        return FakeTargetAdmissionReport()

    monkeypatch.setattr(
        sys,
        "argv",
        [
            "reputation-controller",
            "--config",
            str(config_path),
            "target-admission",
            "--repo",
            "owner/repo",
        ],
    )
    monkeypatch.setattr(
        cli,
        "build_target_admission_report",
        fake_build_target_admission_report,
    )

    result = cli.main()

    assert result == 0
    assert not (tmp_path / ".controller/state/state.json").exists()
    assert '"status": "blocked"' in capsys.readouterr().out
