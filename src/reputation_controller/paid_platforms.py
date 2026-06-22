"""Read-only paid platform scout adapters."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from urllib.parse import urlparse

from .config import ControllerConfig, PaidPlatformConfig
from .github import GitHubClient, Issue
from .http_json import HttpJsonClient


DEFAULT_TITLE_DENY_TERMS = [
    "redesign",
    "rewrite",
    "roadmap",
    "proposal",
    "rfc",
    "support for",
    "integration",
    "migration",
    "new design",
]


@dataclass(frozen=True)
class PaidPlatformRawReward:
    platform: str
    external_id: str
    title: str
    url: str
    amount_cents: int
    currency: str
    trying_users: int = 0
    claimer_users: int = 0
    languages: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class PaidPlatformCandidate:
    platform: str
    status: str
    reason: str
    reward_cents: int
    currency: str
    repo: str
    issue_number: int
    title: str
    issue_url: str
    trying_users: int
    claimer_users: int
    labels: list[str] = field(default_factory=list)
    languages: list[str] = field(default_factory=list)
    worker_enabled: bool = False

    def to_dict(self) -> dict:
        return {
            "platform": self.platform,
            "status": self.status,
            "reason": self.reason,
            "reward_cents": self.reward_cents,
            "currency": self.currency,
            "repo": self.repo,
            "issue_number": self.issue_number,
            "title": self.title,
            "issue_url": self.issue_url,
            "trying_users": self.trying_users,
            "claimer_users": self.claimer_users,
            "labels": self.labels,
            "languages": self.languages,
            "worker_enabled": self.worker_enabled,
        }


@dataclass(frozen=True)
class PaidPlatformReport:
    platform: str
    enabled: bool
    scanned: int
    admitted: list[PaidPlatformCandidate] = field(default_factory=list)
    rejected: list[PaidPlatformCandidate] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "platform": self.platform,
            "enabled": self.enabled,
            "scanned": self.scanned,
            "admitted": [candidate.to_dict() for candidate in self.admitted],
            "rejected": [candidate.to_dict() for candidate in self.rejected],
        }


@dataclass(frozen=True)
class PaidPlatformScoutReport:
    platforms: list[PaidPlatformReport]

    @property
    def admitted(self) -> list[PaidPlatformCandidate]:
        return [candidate for report in self.platforms for candidate in report.admitted]

    @property
    def rejected(self) -> list[PaidPlatformCandidate]:
        return [candidate for report in self.platforms for candidate in report.rejected]

    def to_dict(self) -> dict:
        return {
            "summary": {
                "platforms_scanned": len(
                    [report for report in self.platforms if report.enabled]
                ),
                "rewards_scanned": sum(report.scanned for report in self.platforms),
                "admitted_count": len(self.admitted),
                "rejected_count": len(self.rejected),
                "worker_enabled_count": len(
                    [
                        candidate
                        for candidate in self.admitted
                        if candidate.worker_enabled
                    ]
                ),
            },
            "platforms": [report.to_dict() for report in self.platforms],
        }

    def to_digest(self) -> dict:
        rejection_counts: dict[str, int] = {}
        for candidate in self.rejected:
            rejection_counts[candidate.reason] = (
                rejection_counts.get(candidate.reason, 0) + 1
            )
        return {
            **self.to_dict()["summary"],
            "rejection_counts": rejection_counts,
            "admitted": [candidate.to_dict() for candidate in self.admitted],
        }


class OpireClient:
    def __init__(
        self,
        *,
        endpoint_url: str,
        http: HttpJsonClient | None = None,
    ):
        self.endpoint_url = endpoint_url
        self.http = http or HttpJsonClient()

    def rewards(self) -> list[PaidPlatformRawReward]:
        raw = self.http.get_json(self.endpoint_url)
        if not isinstance(raw, list):
            return []
        rewards: list[PaidPlatformRawReward] = []
        for item in raw:
            if isinstance(item, dict):
                rewards.append(_opire_reward_from_dict(item))
        return rewards


def build_paid_platform_report(
    config: ControllerConfig,
    github: GitHubClient,
    *,
    limit: int = 30,
) -> PaidPlatformScoutReport:
    reports: list[PaidPlatformReport] = []
    for platform in config.paid_platforms:
        if not platform.enabled:
            reports.append(
                PaidPlatformReport(
                    platform=platform.name,
                    enabled=False,
                    scanned=0,
                )
            )
            continue
        rewards = _platform_rewards(platform)[:limit]
        admitted: list[PaidPlatformCandidate] = []
        rejected: list[PaidPlatformCandidate] = []
        for reward in rewards:
            candidate = _candidate_from_reward(reward, platform, github)
            if candidate.status == "admitted":
                admitted.append(candidate)
            else:
                rejected.append(candidate)
        reports.append(
            PaidPlatformReport(
                platform=platform.name,
                enabled=True,
                scanned=len(rewards),
                admitted=admitted,
                rejected=rejected,
            )
        )
    return PaidPlatformScoutReport(reports)


def _platform_rewards(platform: PaidPlatformConfig) -> list[PaidPlatformRawReward]:
    if platform.provider == "opire":
        endpoint = platform.endpoint_url or "https://api.opire.dev/rewards"
        return OpireClient(endpoint_url=endpoint).rewards()
    return []


def _candidate_from_reward(
    reward: PaidPlatformRawReward,
    platform: PaidPlatformConfig,
    github: GitHubClient,
) -> PaidPlatformCandidate:
    parsed = parse_github_issue_url(reward.url)
    repo = ""
    issue_number = 0
    issue = None
    reason = paid_platform_rejection_reason(
        reward,
        platform,
        issue=None,
        existing_open_prs=False,
        parsed_issue=parsed,
    )
    if parsed is not None:
        repo, issue_number = parsed
    if not reason and parsed is not None:
        try:
            issue = github.issue(repo, issue_number)
        except Exception:
            reason = "github_issue_lookup_failed"
    if not reason and issue is not None:
        try:
            existing_open_prs = bool(github.open_prs_for_issue(repo, issue_number))
        except Exception:
            reason = "github_pr_lookup_failed"
            existing_open_prs = False
        if not reason:
            reason = paid_platform_rejection_reason(
                reward,
                platform,
                issue=issue,
                existing_open_prs=existing_open_prs,
                parsed_issue=parsed,
            )
    status = "rejected" if reason else "admitted"
    labels = issue.labels if issue is not None else []
    title = issue.title if issue is not None else reward.title
    issue_url = issue.url if issue is not None else reward.url
    return PaidPlatformCandidate(
        platform=reward.platform,
        status=status,
        reason=reason,
        reward_cents=reward.amount_cents,
        currency=reward.currency,
        repo=repo,
        issue_number=issue_number,
        title=title,
        issue_url=issue_url,
        trying_users=reward.trying_users,
        claimer_users=reward.claimer_users,
        labels=labels,
        languages=reward.languages,
        worker_enabled=False,
    )


def paid_platform_rejection_reason(
    reward: PaidPlatformRawReward,
    platform: PaidPlatformConfig,
    *,
    issue: Issue | None,
    existing_open_prs: bool,
    parsed_issue: tuple[str, int] | None,
) -> str:
    if reward.amount_cents < platform.min_reward_cents:
        return "below_min_reward"
    if parsed_issue is None:
        return "invalid_github_issue_url"
    if reward.trying_users > platform.max_trying_users:
        return "crowded_trying_users"
    if reward.claimer_users > platform.max_claimer_users:
        return "crowded_claimer_users"
    if platform.languages_allow:
        allowed = {language.lower() for language in platform.languages_allow}
        reward_languages = {language.lower() for language in reward.languages}
        if reward_languages and not reward_languages.intersection(allowed):
            return "language_not_allowed"
    if _broad_title_reason(reward.title, platform):
        return "broad_or_nonproof_title"
    if issue is None:
        return ""
    if issue.state.lower() != "open":
        return "issue_not_open"
    if issue.assignees:
        return "assigned"
    labels = {label.lower() for label in issue.labels}
    if labels.intersection(label.lower() for label in platform.labels_deny):
        return "denied_label"
    if existing_open_prs:
        return "existing_open_pr"
    return ""


def parse_github_issue_url(url: str) -> tuple[str, int] | None:
    parsed = urlparse(url)
    if parsed.netloc.lower() != "github.com":
        return None
    parts = [part for part in parsed.path.split("/") if part]
    if len(parts) != 4 or parts[2] != "issues":
        return None
    if not re.fullmatch(r"\d+", parts[3]):
        return None
    return (f"{parts[0]}/{parts[1]}", int(parts[3]))


def _opire_reward_from_dict(data: dict) -> PaidPlatformRawReward:
    pending_price = data.get("pendingPrice", {})
    amount_cents = 0
    currency = ""
    if isinstance(pending_price, dict):
        amount_cents = int(pending_price.get("value") or 0)
        currency = str(pending_price.get("unit") or "")
    languages = [
        str(item)
        for item in data.get("programmingLanguages", [])
        if isinstance(item, str)
    ]
    return PaidPlatformRawReward(
        platform="opire",
        external_id=str(data.get("id", "")),
        title=str(data.get("title", "")),
        url=str(data.get("url", "")),
        amount_cents=amount_cents,
        currency=currency,
        trying_users=len(data.get("tryingUsers", [])),
        claimer_users=len(data.get("claimerUsers", [])),
        languages=languages,
    )


def _broad_title_reason(
    title: str,
    platform: PaidPlatformConfig,
) -> str:
    normalized = title.strip().lower()
    if len(normalized.split()) < 3:
        return "broad_or_nonproof_title"
    denied_terms = platform.title_deny_terms or DEFAULT_TITLE_DENY_TERMS
    if any(term.lower() in normalized for term in denied_terms):
        return "broad_or_nonproof_title"
    if normalized.startswith(("add ", "feat", "feature", "chore", "docs", "refactor")):
        return "broad_or_nonproof_title"
    return ""
