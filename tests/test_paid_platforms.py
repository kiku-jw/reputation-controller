import urllib.error

from reputation_controller.config import ControllerConfig, PaidPlatformConfig
from reputation_controller.github import Issue, PullRequest
from reputation_controller.paid_platforms import (
    HttpJsonClient,
    OpireClient,
    PaidPlatformRawReward,
    build_paid_platform_report,
    paid_platform_rejection_reason,
    parse_github_issue_url,
)


class FakeGitHub:
    def __init__(self, issues_by_key, prs_by_key=None):
        self.issues_by_key = issues_by_key
        self.prs_by_key = prs_by_key or {}
        self.issue_calls = []
        self.pr_calls = []

    def issue(self, repo_name: str, issue_number: int):
        self.issue_calls.append((repo_name, issue_number))
        return self.issues_by_key[(repo_name, issue_number)]

    def open_prs_for_issue(self, repo_name: str, issue_number: int):
        self.pr_calls.append((repo_name, issue_number))
        return self.prs_by_key.get((repo_name, issue_number), [])


class FakeHttp:
    def __init__(self, payload):
        self.payload = payload

    def get_json(self, url: str):
        return self.payload


class FakeResponse:
    def read(self):
        return b'{"ok": true}'

    def close(self):
        return None


def make_platform() -> PaidPlatformConfig:
    return PaidPlatformConfig(
        name="opire",
        provider="opire",
        endpoint_url="https://api.opire.dev/rewards",
        min_reward_cents=10000,
        max_trying_users=3,
        max_claimer_users=0,
        labels_deny=["dependencies"],
        languages_allow=["Python", "TypeScript"],
    )


def make_reward(**overrides) -> PaidPlatformRawReward:
    data = {
        "platform": "opire",
        "external_id": "reward-1",
        "title": "Fix export crash on empty file",
        "url": "https://github.com/acme/widgets/issues/42",
        "amount_cents": 15000,
        "currency": "USD_CENT",
        "trying_users": 0,
        "claimer_users": 0,
        "languages": ["Python"],
    }
    data.update(overrides)
    return PaidPlatformRawReward(**data)


def test_parse_github_issue_url_accepts_only_issue_urls():
    assert parse_github_issue_url("https://github.com/acme/widgets/issues/42") == (
        "acme/widgets",
        42,
    )
    assert parse_github_issue_url("https://github.com/acme/widgets/pull/42") is None
    assert parse_github_issue_url("https://example.com/acme/widgets/issues/42") is None


def test_opire_client_normalizes_rewards():
    payload = [
        {
            "id": "01",
            "title": "Fix API timeout",
            "url": "https://github.com/acme/widgets/issues/42",
            "pendingPrice": {"value": 12000, "unit": "USD_CENT"},
            "tryingUsers": [{"username": "one"}],
            "claimerUsers": [],
            "programmingLanguages": ["Python"],
        }
    ]

    rewards = OpireClient(
        endpoint_url="https://api.opire.dev/rewards",
        http=FakeHttp(payload),
    ).rewards()

    assert rewards[0].platform == "opire"
    assert rewards[0].amount_cents == 12000
    assert rewards[0].trying_users == 1
    assert rewards[0].languages == ["Python"]


def test_http_json_client_retries_with_certifi_context(monkeypatch):
    calls = []
    fake_context = object()

    def fake_urlopen(request, timeout, context=None):
        calls.append((request, timeout, context))
        if len(calls) == 1:
            raise urllib.error.URLError("certificate verify failed")
        return FakeResponse()

    monkeypatch.setattr(
        "reputation_controller.http_json.urllib.request.urlopen",
        fake_urlopen,
    )
    monkeypatch.setattr(
        "reputation_controller.http_json._certifi_ssl_context",
        lambda: fake_context,
    )

    payload = HttpJsonClient().get_json("https://api.opire.dev/rewards")

    assert payload == {"ok": True}
    assert calls[0][2] is None
    assert calls[1][2] is fake_context


def test_paid_platform_admission_rejects_non_proof_candidates():
    platform = make_platform()

    assert (
        paid_platform_rejection_reason(
            make_reward(amount_cents=9999),
            platform,
            issue=None,
            existing_open_prs=False,
            parsed_issue=("acme/widgets", 42),
        )
        == "below_min_reward"
    )
    assert (
        paid_platform_rejection_reason(
            make_reward(url="https://example.com/issues/42"),
            platform,
            issue=None,
            existing_open_prs=False,
            parsed_issue=None,
        )
        == "invalid_github_issue_url"
    )
    assert (
        paid_platform_rejection_reason(
            make_reward(trying_users=4),
            platform,
            issue=None,
            existing_open_prs=False,
            parsed_issue=("acme/widgets", 42),
        )
        == "crowded_trying_users"
    )
    assert (
        paid_platform_rejection_reason(
            make_reward(title="Add support for another backend"),
            platform,
            issue=None,
            existing_open_prs=False,
            parsed_issue=("acme/widgets", 42),
        )
        == "broad_or_nonproof_title"
    )


def test_build_paid_platform_report_admits_review_only_candidate(monkeypatch):
    reward = make_reward()
    config = ControllerConfig(
        workspace="/tmp/oss-controller",
        state_dir=".controller/state",
        dry_run=True,
        paid_platforms=[make_platform()],
    )
    github = FakeGitHub(
        {
            ("acme/widgets", 42): Issue(
                repo="acme/widgets",
                number=42,
                title="Fix export crash on empty file",
                url="https://github.com/acme/widgets/issues/42",
                labels=["bug"],
                assignees=[],
                state="open",
            )
        }
    )

    monkeypatch.setattr(
        "reputation_controller.paid_platforms._platform_rewards",
        lambda platform: [reward],
    )
    report = build_paid_platform_report(config, github, limit=10)

    assert len(report.admitted) == 1
    assert report.admitted[0].worker_enabled is False
    assert report.to_dict()["summary"]["worker_enabled_count"] == 0
    assert github.issue_calls == [("acme/widgets", 42)]
    assert github.pr_calls == [("acme/widgets", 42)]


def test_build_paid_platform_report_rejects_existing_open_pr(monkeypatch):
    reward = make_reward()
    config = ControllerConfig(
        workspace="/tmp/oss-controller",
        state_dir=".controller/state",
        dry_run=True,
        paid_platforms=[make_platform()],
    )
    github = FakeGitHub(
        {
            ("acme/widgets", 42): Issue(
                repo="acme/widgets",
                number=42,
                title="Fix export crash on empty file",
                url="https://github.com/acme/widgets/issues/42",
                labels=["bug"],
                assignees=[],
                state="open",
            )
        },
        {
            ("acme/widgets", 42): [
                PullRequest(
                    number=43,
                    title="Fix export crash",
                    url="https://github.com/acme/widgets/pull/43",
                )
            ]
        },
    )

    monkeypatch.setattr(
        "reputation_controller.paid_platforms._platform_rewards",
        lambda platform: [reward],
    )
    report = build_paid_platform_report(config, github, limit=10)

    assert report.admitted == []
    assert report.rejected[0].reason == "existing_open_pr"
