import json
from pathlib import Path

from reputation_controller.config import load_config
from reputation_controller.config import RepoConfig
from reputation_controller.controller import (
    ReputationController,
    _issue_admitted,
    _public_claim_reason,
)
from reputation_controller.github import Issue, IssueComment
from reputation_controller.state import ControllerState, Sprint, StateStore


class FakeGitHub:
    def __init__(self, comments_by_issue=None):
        self.scanned_repos = []
        self.comments_by_issue = comments_by_issue or {}

    def list_open_issues(self, repo_name: str, *, limit: int = 30):
        self.scanned_repos.append(repo_name)
        return [
            Issue(
                repo=repo_name,
                number=1197,
                title="Cypress E2E still failing on Windows after setup fixes",
                url="https://github.com/fossasia/visdom/issues/1197",
                labels=["bug"],
                assignees=[],
                updated_at="2026-06-13T00:00:00Z",
            ),
            Issue(
                repo=repo_name,
                number=1451,
                title="chore(deps): bump Cypress",
                url="https://github.com/fossasia/visdom/issues/1451",
                labels=["dependencies"],
                assignees=[],
                updated_at="2026-06-13T00:00:00Z",
            ),
        ]

    def issue_comments(self, repo_name: str, issue_number: int):
        return self.comments_by_issue.get(issue_number, [])

    def open_prs_for_issue(self, repo_name: str, issue_number: int):
        return []


def write_config(tmp_path: Path) -> Path:
    path = tmp_path / "controller.json"
    path.write_text(
        json.dumps(
            {
                "workspace": str(tmp_path),
                "state_dir": ".controller/state",
                "dry_run": True,
                "limits": {
                    "max_active_sprints": 1,
                    "max_active_targets": 3,
                    "max_open_hypotheses": 5,
                },
                "policy": {
                    "allow_public_comments": False,
                    "allow_pr_create": False,
                    "allow_force_push": False,
                    "forbidden_title_terms": ["codex"],
                },
                "repos": [
                    {
                        "name": "fossasia/visdom",
                        "local_path": "visdom",
                        "default_branch": "dev",
                        "enabled": True,
                        "labels_deny": ["dependencies"],
                    }
                ],
            }
        )
    )
    return path


def test_run_once_creates_dry_run_task_packet_and_state(tmp_path: Path):
    config = load_config(write_config(tmp_path))
    state_store = StateStore(tmp_path / ".controller/state/state.json")
    controller = ReputationController(config, FakeGitHub(), state_store)

    result = controller.run_once()

    assert result.status == "packet_created"
    assert result.public_actions == []
    assert result.packet_path is not None
    packet_text = result.packet_path.read_text()
    assert "fossasia/visdom#1197" in packet_text
    assert "Forbidden actions" in packet_text
    assert "Open a PR" in packet_text
    state = state_store.load()
    assert state.active_sprints[0].sprint_id == "fossasia-visdom-1197"


def test_run_once_stops_when_wip_gate_is_closed(tmp_path: Path):
    config = load_config(write_config(tmp_path))
    state_store = StateStore(tmp_path / ".controller/state/state.json")
    state_store.save(
        ControllerState.from_dict(
            {
                "active_sprints": [
                    {
                        "sprint_id": "fossasia-visdom-1197",
                        "repo": "fossasia/visdom",
                        "issue_number": 1197,
                        "title": "Existing sprint",
                        "status": "packet_created",
                    }
                ],
                "open_hypotheses": [],
                "target_history": [],
                "events": [],
            }
        )
    )
    controller = ReputationController(config, FakeGitHub(), state_store)

    result = controller.run_once()

    assert result.status == "blocked_by_gate"
    assert result.gate_code == "max_active_sprints"
    assert result.packet_path is None


def test_run_once_skips_resolved_sprints(tmp_path: Path):
    config = load_config(write_config(tmp_path))
    state_store = StateStore(tmp_path / ".controller/state/state.json")
    state_store.save(
        ControllerState(
            completed_sprints=[
                Sprint(
                    sprint_id="fossasia-visdom-1197",
                    repo="fossasia/visdom",
                    issue_number=1197,
                    title="Cypress E2E still failing",
                    status="proof",
                )
            ]
        )
    )
    controller = ReputationController(config, FakeGitHub(), state_store)

    result = controller.run_once()

    assert result.status == "no_candidate"
    assert result.diagnostics is not None
    assert result.diagnostics["issues_scanned"] == 2
    assert result.diagnostics["worker_admitted_count"] == 0
    assert result.packet_path is None
    state = state_store.load()
    assert state.active_sprints == []
    assert state.events[-1]["type"] == "no_candidate"
    assert "top_rejection_reasons" in state.events[-1]["message"]


def test_run_once_does_not_turn_paid_platforms_into_worker_packets(tmp_path: Path):
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
    config = load_config(config_path)
    state_store = StateStore(tmp_path / ".controller/state/state.json")
    controller = ReputationController(config, FakeGitHub(), state_store)

    result = controller.run_once()

    assert result.status == "no_candidate"
    assert result.packet_path is None
    assert state_store.load().active_sprints == []


def test_run_once_skips_issue_with_existing_pr_comment(tmp_path: Path):
    config = load_config(write_config(tmp_path))
    state_store = StateStore(tmp_path / ".controller/state/state.json")
    controller = ReputationController(
        config,
        FakeGitHub(
            comments_by_issue={
                1197: [
                    IssueComment(
                        author="other-user",
                        body="PR #1353 implements this fix.",
                    )
                ]
            }
        ),
        state_store,
    )

    result = controller.run_once()

    assert result.status == "no_candidate"
    state = state_store.load()
    assert state.active_sprints == []
    assert state.events[0]["type"] == "candidate_skipped"
    assert "existing_pr_mentioned" in state.events[0]["message"]


def test_issue_admission_rejects_broad_feature_request():
    issue = Issue(
        repo="fossasia/visdom",
        number=1205,
        title="[Feature Request] PyTorch-Native Deep Integration",
        url="https://github.com/fossasia/visdom/issues/1205",
    )
    repo = RepoConfig(
        name="fossasia/visdom",
        local_path="visdom",
        default_branch="dev",
    )

    assert _issue_admitted(issue, repo) is False


def test_issue_admission_rejects_broad_setup_request():
    issue = Issue(
        repo="fossasia/visdom",
        number=1167,
        title="Add testing setup and initial test cases",
        url="https://github.com/fossasia/visdom/issues/1167",
    )
    repo = RepoConfig(
        name="fossasia/visdom",
        local_path="visdom",
        default_branch="dev",
    )

    assert _issue_admitted(issue, repo) is False


def test_issue_admission_rejects_enhancement_title():
    issue = Issue(
        repo="fossasia/visdom",
        number=1133,
        title="Enhancement: Improve save_env endpoint",
        url="https://github.com/fossasia/visdom/issues/1133",
    )
    repo = RepoConfig(
        name="fossasia/visdom",
        local_path="visdom",
        default_branch="dev",
    )

    assert _issue_admitted(issue, repo) is False


def test_issue_admission_rejects_redesign_ui_title():
    issue = Issue(
        repo="fossasia/visdom",
        number=1121,
        title="Redesign main dashboard layout for improved UI/UX",
        url="https://github.com/fossasia/visdom/issues/1121",
    )
    repo = RepoConfig(
        name="fossasia/visdom",
        local_path="visdom",
        default_branch="dev",
    )

    assert _issue_admitted(issue, repo) is False


def test_public_claim_reason_handles_curly_apostrophe_claim():
    comments = [
        IssueComment(
            author="other-user",
            body=(
                "Agreed, I’ll align Cypress config across environments and add "
                "render-stabilization on Windows, then rebaseline and verify."
            ),
        )
    ]

    assert (
        _public_claim_reason(comments, github_actor="kiku-jw") == "claimed_by_comment"
    )


def test_public_claim_reason_handles_work_on_this_pr_claim():
    comments = [
        IssueComment(
            author="other-user",
            body="Hi, I'd like to work on this. I'll submit a PR shortly.",
        )
    ]

    assert (
        _public_claim_reason(comments, github_actor="kiku-jw") == "claimed_by_comment"
    )


def test_public_claim_reason_handles_already_implemented_pr_claim():
    comments = [
        IssueComment(
            author="other-user",
            body=(
                "I’ve already implemented a redesign of the dashboard layout. "
                "I’ll be opening a PR for this shortly."
            ),
        )
    ]

    assert (
        _public_claim_reason(comments, github_actor="kiku-jw") == "claimed_by_comment"
    )
