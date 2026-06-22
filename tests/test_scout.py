from reputation_controller.config import ControllerConfig, PolicyConfig, RepoConfig
from reputation_controller.github import Issue, IssueComment, PullRequest
from reputation_controller.repo_health import RepoHealthReport
from reputation_controller.scout import (
    build_digest,
    build_scout_report,
    first_worker_candidate,
)
from reputation_controller.state import ControllerState, Sprint


class FakeGitHub:
    def __init__(self, issues_by_repo, comments_by_issue=None, prs_by_issue=None):
        self.issues_by_repo = issues_by_repo
        self.comments_by_issue = comments_by_issue or {}
        self.prs_by_issue = prs_by_issue or {}
        self.comment_calls = []
        self.pr_calls = []

    def list_open_issues(self, repo_name: str, *, limit: int = 30):
        return self.issues_by_repo.get(repo_name, [])[:limit]

    def issue_comments(self, repo_name: str, issue_number: int):
        self.comment_calls.append((repo_name, issue_number))
        return self.comments_by_issue.get((repo_name, issue_number), [])

    def open_prs_for_issue(self, repo_name: str, issue_number: int):
        self.pr_calls.append((repo_name, issue_number))
        return self.prs_by_issue.get((repo_name, issue_number), [])


class FailingListGitHub(FakeGitHub):
    def list_open_issues(self, repo_name: str, *, limit: int = 30):
        raise RuntimeError("gh command timed out")


class FailingDeepGitHub(FakeGitHub):
    def issue_comments(self, repo_name: str, issue_number: int):
        raise RuntimeError("comment lookup failed")


def make_config() -> ControllerConfig:
    return ControllerConfig(
        workspace="/tmp/oss-controller",
        state_dir=".controller/state",
        dry_run=False,
        github_actor="kiku-jw",
        policy=PolicyConfig(
            allow_public_comments=True,
            allow_pr_create=False,
            allow_force_push=False,
            public_action_mode="issue-comment",
        ),
        repos=[
            RepoConfig(
                name="fossasia/visdom",
                local_path="visdom",
                default_branch="dev",
                enabled=True,
                worker_enabled=True,
                labels_deny=["dependencies"],
            ),
            RepoConfig(
                name="giskard-ai/giskard",
                local_path="giskard-oss",
                default_branch="main",
                enabled=True,
                worker_enabled=False,
                labels_deny=["dependencies"],
            ),
        ],
    )


def test_scout_reports_admitted_and_rejected_issues_without_state_mutation():
    github = FakeGitHub(
        {
            "fossasia/visdom": [
                Issue(
                    repo="fossasia/visdom",
                    number=1,
                    title="Fix lazy env path lookup",
                    url="https://github.com/fossasia/visdom/issues/1",
                    labels=["bug"],
                ),
                Issue(
                    repo="fossasia/visdom",
                    number=2,
                    title="Add new dashboard",
                    url="https://github.com/fossasia/visdom/issues/2",
                    labels=[],
                ),
                Issue(
                    repo="fossasia/visdom",
                    number=3,
                    title="Fix claimed issue",
                    url="https://github.com/fossasia/visdom/issues/3",
                    labels=["bug"],
                ),
            ],
            "giskard-ai/giskard": [
                Issue(
                    repo="giskard-ai/giskard",
                    number=4,
                    title="Fix report export crash",
                    url="https://github.com/giskard-ai/giskard/issues/4",
                    labels=["bug"],
                )
            ],
        },
        {
            ("fossasia/visdom", 3): [
                IssueComment(
                    author="other-user",
                    body="I am working on this issue.",
                )
            ]
        },
    )
    state = ControllerState(
        completed_sprints=[
            Sprint(
                sprint_id="fossasia-visdom-1",
                repo="fossasia/visdom",
                issue_number=1,
                title="Fix lazy env path lookup",
                status="proof",
            )
        ]
    )

    report = build_scout_report(make_config(), github, state, limit=10)

    assert report.to_dict()["summary"]["repos_scanned"] == 2
    assert [item.issue.number for item in report.admitted] == [4]
    assert {item.reason for item in report.rejected} == {
        "resolved_or_active_sprint",
        "broad_or_nonproof_title",
        "claimed_by_comment",
    }
    assert state.active_sprints == []


def test_worker_only_scout_ignores_scout_only_repos():
    github = FakeGitHub(
        {
            "giskard-ai/giskard": [
                Issue(
                    repo="giskard-ai/giskard",
                    number=4,
                    title="Fix report export crash",
                    url="https://github.com/giskard-ai/giskard/issues/4",
                    labels=["bug"],
                )
            ]
        }
    )

    report = build_scout_report(
        make_config(),
        github,
        ControllerState(),
        worker_only=True,
    )

    assert report.admitted == []
    assert first_worker_candidate(report) is None


def test_scout_records_repo_error_instead_of_raising():
    report = build_scout_report(make_config(), FailingListGitHub({}), ControllerState())

    assert report.repos[0].error == "github_issue_list_failed"
    assert report.to_dict()["repos"][0]["error"] == "github_issue_list_failed"


def test_scout_rejects_issue_when_deep_lookup_fails():
    github = FailingDeepGitHub(
        {
            "fossasia/visdom": [
                Issue(
                    repo="fossasia/visdom",
                    number=10,
                    title="Fix import crash",
                    url="https://github.com/fossasia/visdom/issues/10",
                    labels=["bug"],
                )
            ]
        }
    )

    report = build_scout_report(make_config(), github, ControllerState())

    assert report.admitted == []
    assert report.rejected[0].reason == "github_comment_lookup_failed"
    assert report.to_dict()["summary"]["rejected_count"] == 1


def test_worker_issue_allowlist_only_applies_to_worker_scout():
    config = make_config()
    config.repos[1].worker_enabled = True
    config.repos[1].worker_issue_allow = [2499]
    github = FakeGitHub(
        {
            "giskard-ai/giskard": [
                Issue(
                    repo="giskard-ai/giskard",
                    number=2523,
                    title="Handle input-generation errors like check errors",
                    url="https://github.com/giskard-ai/giskard/issues/2523",
                    labels=["bug"],
                ),
                Issue(
                    repo="giskard-ai/giskard",
                    number=2499,
                    title="giskard-checks: validate Suite.run(max_concurrency)",
                    url="https://github.com/giskard-ai/giskard/issues/2499",
                    labels=[],
                ),
            ]
        }
    )

    full_report = build_scout_report(config, github, ControllerState())
    worker_report = build_scout_report(
        config,
        github,
        ControllerState(),
        worker_only=True,
    )

    assert [item.issue.number for item in full_report.admitted] == [2523, 2499]
    assert [item.issue.number for item in worker_report.admitted] == [2499]
    assert worker_report.rejected[0].reason == "not_in_worker_issue_allowlist"


def test_scout_rejects_issue_with_existing_open_pr():
    config = make_config()
    config.repos[1].worker_enabled = True
    config.repos[1].worker_issue_allow = [2511]
    github = FakeGitHub(
        {
            "giskard-ai/giskard": [
                Issue(
                    repo="giskard-ai/giskard",
                    number=2511,
                    title="JsonValid rejects already parsed string values",
                    url="https://github.com/giskard-ai/giskard/issues/2511",
                    labels=[],
                )
            ]
        },
        prs_by_issue={
            ("giskard-ai/giskard", 2511): [
                PullRequest(
                    number=2512,
                    title="fix(checks): accept parsed string JSON values",
                    url="https://github.com/giskard-ai/giskard/pull/2512",
                    author="harsh21234i",
                )
            ]
        },
    )

    report = build_scout_report(
        config,
        github,
        ControllerState(),
        worker_only=True,
    )

    assert report.admitted == []
    assert report.rejected[0].reason == "existing_open_pr"
    assert github.pr_calls == [("giskard-ai/giskard", 2511)]


def test_scout_can_skip_deep_github_checks_for_fast_digest():
    config = make_config()
    github = FakeGitHub(
        {
            "fossasia/visdom": [
                Issue(
                    repo="fossasia/visdom",
                    number=10,
                    title="Fix import crash",
                    url="https://github.com/fossasia/visdom/issues/10",
                    labels=["bug"],
                )
            ]
        },
        comments_by_issue={
            ("fossasia/visdom", 10): [
                IssueComment(author="other-user", body="I am working on this issue.")
            ]
        },
        prs_by_issue={
            ("fossasia/visdom", 10): [
                PullRequest(
                    number=11,
                    title="Fix import crash",
                    url="https://github.com/fossasia/visdom/pull/11",
                    author="other-user",
                )
            ]
        },
    )

    report = build_scout_report(config, github, ControllerState(), deep_checks=False)

    assert [item.issue.number for item in report.admitted] == [10]
    assert github.comment_calls == []
    assert github.pr_calls == []
    assert report.to_dict()["summary"]["deep_checks"] is False


def test_digest_summarizes_policy_state_and_rejections():
    config = make_config()
    github = FakeGitHub(
        {
            "fossasia/visdom": [
                Issue(
                    repo="fossasia/visdom",
                    number=2,
                    title="Add new dashboard",
                    url="https://github.com/fossasia/visdom/issues/2",
                    labels=[],
                )
            ]
        }
    )
    state = ControllerState(
        active_sprints=[
            Sprint(
                sprint_id="fossasia-visdom-99",
                repo="fossasia/visdom",
                issue_number=99,
                title="Active sprint",
                status="packet_created",
            )
        ]
    )
    report = build_scout_report(config, github, state)

    digest = build_digest(report, state, config)

    assert digest["state"]["active_sprints"] == 1
    assert digest["policy"]["public_action_mode"] == "issue-comment"
    assert digest["scout"]["rejection_counts"] == {"broad_or_nonproof_title": 1}
    assert digest["scout"]["scout_only_repos"] == ["giskard-ai/giskard"]


def test_digest_can_include_repo_health_without_changing_scout_summary():
    config = make_config()
    state = ControllerState()
    report = build_scout_report(config, FakeGitHub({"fossasia/visdom": []}), state)

    digest = build_digest(
        report,
        state,
        config,
        repo_health_reports=[
            RepoHealthReport(
                repo="fossasia/visdom",
                status="downgrade",
                source_url="https://api.scorecard.dev/projects/github.com/fossasia/visdom",
                advisory_reasons=["weak_ci_tests"],
            )
        ],
    )

    assert digest["scout"]["issues_scanned"] == 0
    assert digest["repo_health"]["repos_checked"] == 1
    assert digest["repo_health"]["downgrade_count"] == 1
    assert digest["repo_health"]["reports"][0]["advisory_reasons"] == ["weak_ci_tests"]


def test_digest_can_include_paid_platform_and_pr_watch_visibility():
    config = make_config()
    state = ControllerState()
    report = build_scout_report(config, FakeGitHub({"fossasia/visdom": []}), state)

    digest = build_digest(
        report,
        state,
        config,
        paid_platform_summary={
            "admitted_count": 1,
            "rejection_counts": {"crowded_trying_users": 2},
        },
        pr_watch_summary={
            "status": "ok",
            "open_count": 2,
            "needs_attention_count": 0,
        },
    )

    assert digest["scout"]["issues_scanned"] == 0
    assert digest["paid_platforms"]["admitted_count"] == 1
    assert digest["pr_watch"]["open_count"] == 2
