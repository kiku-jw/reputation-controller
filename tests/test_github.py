import json
import subprocess

import pytest

from reputation_controller.config import Secrets
from reputation_controller.github import GitHubClient, run_command


def test_github_client_uses_gh_cli_and_redacts_token_from_result():
    calls = []

    def fake_run(command, env):
        calls.append((command, env))
        return json.dumps(
            [
                {
                    "number": 1197,
                    "title": "Cypress E2E still failing",
                    "url": "https://github.com/fossasia/visdom/issues/1197",
                    "labels": [{"name": "bug"}],
                    "assignees": [],
                    "updatedAt": "2026-06-13T00:00:00Z",
                }
            ]
        )

    client = GitHubClient(
        secrets=Secrets(github_token="fake-github-token"),
        command_runner=fake_run,
    )

    issues = client.list_open_issues("fossasia/visdom")

    assert issues[0].number == 1197
    assert calls[0][0][:4] == ["gh", "issue", "list", "--repo"]
    assert calls[0][1]["GH_TOKEN"] == "fake-github-token"
    assert calls[0][1]["CONTROLLER_GH_TIMEOUT_SECONDS"] == "60.0"
    assert "fake-github-token" not in repr(issues[0])


def test_github_client_passes_configured_timeout_to_runner():
    calls = []

    def fake_run(command, env):
        calls.append((command, env))
        return "[]"

    client = GitHubClient(
        secrets=Secrets(github_token="fake-github-token"),
        timeout_seconds=12.5,
        command_runner=fake_run,
    )

    client.list_open_issues("fossasia/visdom")

    assert calls[0][1]["CONTROLLER_GH_TIMEOUT_SECONDS"] == "12.5"


def test_github_client_reads_issue_comments():
    calls = []

    def fake_run(command, env):
        calls.append((command, env))
        return json.dumps(
            {
                "comments": [
                    {
                        "author": {"login": "contributor"},
                        "body": "PR #1353 implements this fix.",
                        "url": "https://github.com/fossasia/visdom/issues/1331#x",
                    }
                ]
            }
        )

    client = GitHubClient(
        secrets=Secrets(github_token="fake-github-token"),
        command_runner=fake_run,
    )

    comments = client.issue_comments("fossasia/visdom", 1331)

    assert comments[0].author == "contributor"
    assert comments[0].body == "PR #1353 implements this fix."
    assert calls[0][0][:4] == ["gh", "issue", "view", "1331"]
    assert calls[0][1]["GH_TOKEN"] == "fake-github-token"


def test_github_client_reads_single_issue_state():
    calls = []

    def fake_run(command, env):
        calls.append((command, env))
        return json.dumps(
            {
                "number": 42,
                "title": "Fix export crash",
                "url": "https://github.com/acme/widgets/issues/42",
                "labels": [{"name": "bug"}],
                "assignees": [{"login": "maintainer"}],
                "updatedAt": "2026-06-13T00:00:00Z",
                "state": "OPEN",
            }
        )

    client = GitHubClient(
        secrets=Secrets(github_token="fake-github-token"),
        command_runner=fake_run,
    )

    issue = client.issue("acme/widgets", 42)

    assert issue.repo == "acme/widgets"
    assert issue.number == 42
    assert issue.state == "OPEN"
    assert issue.labels == ["bug"]
    assert issue.assignees == ["maintainer"]
    assert calls[0][0][:4] == ["gh", "issue", "view", "42"]


def test_run_command_passes_configured_timeout(monkeypatch):
    calls = []

    def fake_run(command, **kwargs):
        calls.append((command, kwargs))
        return subprocess.CompletedProcess(command, 0, stdout="[]", stderr="")

    monkeypatch.setattr("reputation_controller.github.subprocess.run", fake_run)

    output = run_command(
        ["gh", "issue", "list"],
        {"CONTROLLER_GH_TIMEOUT_SECONDS": "7.5"},
    )

    assert output == "[]"
    assert calls[0][0] == ["gh", "issue", "list"]
    assert calls[0][1]["timeout"] == 7.5


def test_run_command_wraps_timeout(monkeypatch):
    def fake_run(command, **kwargs):
        raise subprocess.TimeoutExpired(command, timeout=kwargs["timeout"])

    monkeypatch.setattr("reputation_controller.github.subprocess.run", fake_run)

    with pytest.raises(RuntimeError, match="gh command timed out after 60s"):
        run_command(["gh", "issue", "view", "42"], {})
