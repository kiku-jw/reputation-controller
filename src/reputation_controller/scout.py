"""Read-only issue scouting and admission policy."""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from .config import ControllerConfig, RepoConfig
from .github import GitHubClient, Issue, IssueComment, PullRequest
from .repo_health import RepoHealthReport
from .state import ControllerState


@dataclass
class ScoutIssue:
    issue: Issue
    status: str
    reason: str = ""
    worker_enabled: bool = True

    def to_dict(self) -> dict:
        return {
            "repo": self.issue.repo,
            "number": self.issue.number,
            "title": self.issue.title,
            "url": self.issue.url,
            "labels": self.issue.labels,
            "assignees": self.issue.assignees,
            "status": self.status,
            "reason": self.reason,
            "worker_enabled": self.worker_enabled,
        }


@dataclass
class ScoutRepoReport:
    repo: str
    enabled: bool
    worker_enabled: bool
    scanned: int = 0
    error: str = ""
    admitted: list[ScoutIssue] = field(default_factory=list)
    rejected: list[ScoutIssue] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "repo": self.repo,
            "enabled": self.enabled,
            "worker_enabled": self.worker_enabled,
            "scanned": self.scanned,
            "error": self.error,
            "admitted": [item.to_dict() for item in self.admitted],
            "rejected": [item.to_dict() for item in self.rejected],
        }


@dataclass
class ScoutReport:
    repos: list[ScoutRepoReport]
    deep_checks: bool = True

    @property
    def admitted(self) -> list[ScoutIssue]:
        return [item for repo in self.repos for item in repo.admitted]

    @property
    def rejected(self) -> list[ScoutIssue]:
        return [item for repo in self.repos for item in repo.rejected]

    def to_dict(self) -> dict:
        return {
            "summary": {
                "repos_scanned": len([repo for repo in self.repos if repo.enabled]),
                "issues_scanned": sum(repo.scanned for repo in self.repos),
                "admitted_count": len(self.admitted),
                "rejected_count": len(self.rejected),
                "deep_checks": self.deep_checks,
            },
            "repos": [repo.to_dict() for repo in self.repos],
        }


def build_scout_report(
    config: ControllerConfig,
    github: GitHubClient,
    state: ControllerState | None = None,
    *,
    limit: int = 30,
    worker_only: bool = False,
    deep_checks: bool = True,
) -> ScoutReport:
    seen_sprint_ids = _seen_sprint_ids(state)
    repo_reports: list[ScoutRepoReport] = []
    for repo in config.repos:
        repo_report = ScoutRepoReport(
            repo=repo.name,
            enabled=repo.enabled,
            worker_enabled=repo.worker_enabled,
        )
        if not repo.enabled:
            repo_reports.append(repo_report)
            continue
        if worker_only and not repo.worker_enabled:
            repo_reports.append(repo_report)
            continue

        try:
            issues = github.list_open_issues(repo.name, limit=limit)
        except Exception:
            repo_report.error = "github_issue_list_failed"
            repo_reports.append(repo_report)
            continue
        repo_report.scanned = len(issues)
        for issue in issues:
            reason = admission_rejection_reason(
                issue,
                repo,
                seen_sprint_ids=seen_sprint_ids,
                worker_only=worker_only,
            )
            if not reason and deep_checks:
                try:
                    comments = github.issue_comments(issue.repo, issue.number)
                except Exception:
                    reason = "github_comment_lookup_failed"
                if not reason:
                    reason = public_claim_reason(comments, config.github_actor)
            if not reason and deep_checks:
                try:
                    prs = github.open_prs_for_issue(issue.repo, issue.number)
                except Exception:
                    reason = "github_pr_lookup_failed"
                if not reason:
                    reason = open_pr_reason(prs, config.github_actor)
            scout_issue = ScoutIssue(
                issue=issue,
                status="rejected" if reason else "admitted",
                reason=reason,
                worker_enabled=repo.worker_enabled,
            )
            if reason:
                repo_report.rejected.append(scout_issue)
            else:
                repo_report.admitted.append(scout_issue)
        repo_reports.append(repo_report)
    return ScoutReport(repo_reports, deep_checks=deep_checks)


def first_worker_candidate(report: ScoutReport) -> Issue | None:
    for item in report.admitted:
        if item.worker_enabled:
            return item.issue
    return None


def scout_diagnostics(report: ScoutReport) -> dict:
    rejection_counts: dict[str, int] = {}
    for item in report.rejected:
        rejection_counts[item.reason] = rejection_counts.get(item.reason, 0) + 1
    top_rejection_reasons = [
        {"reason": reason, "count": count}
        for reason, count in sorted(
            rejection_counts.items(),
            key=lambda item: (-item[1], item[0]),
        )[:5]
    ]
    return {
        "repos_scanned": len([repo for repo in report.repos if repo.enabled]),
        "worker_repos_scanned": len(
            [repo for repo in report.repos if repo.enabled and repo.worker_enabled]
        ),
        "issues_scanned": sum(repo.scanned for repo in report.repos),
        "admitted_count": len(report.admitted),
        "worker_admitted_count": len(
            [item for item in report.admitted if item.worker_enabled]
        ),
        "rejected_count": len(report.rejected),
        "repo_errors": [
            {"repo": repo.repo, "error": repo.error}
            for repo in report.repos
            if repo.error
        ],
        "top_rejection_reasons": top_rejection_reasons,
    }


def build_digest(
    report: ScoutReport,
    state: ControllerState,
    config: ControllerConfig,
    *,
    repo_health_reports: list[RepoHealthReport] | None = None,
    paid_platform_summary: dict | None = None,
    pr_watch_summary: dict | None = None,
) -> dict:
    rejection_counts: dict[str, int] = {}
    for item in report.rejected:
        rejection_counts[item.reason] = rejection_counts.get(item.reason, 0) + 1
    digest = {
        "state": {
            "active_sprints": len(state.active_sprints),
            "completed_sprints": len(state.completed_sprints),
            "open_hypotheses": len(state.open_hypotheses),
        },
        "policy": {
            "dry_run": config.dry_run,
            "public_action_mode": config.policy.public_action_mode,
            "allow_public_comments": config.policy.allow_public_comments,
            "allow_pr_create": config.policy.allow_pr_create,
            "allow_force_push": config.policy.allow_force_push,
            "worker_execution": config.worker.allow_execution,
        },
        "scout": {
            "repos_scanned": len([repo for repo in report.repos if repo.enabled]),
            "issues_scanned": sum(repo.scanned for repo in report.repos),
            "admitted_count": len(report.admitted),
            "rejected_count": len(report.rejected),
            "deep_checks": report.deep_checks,
            "rejection_counts": rejection_counts,
            "repo_errors": [
                {"repo": repo.repo, "error": repo.error}
                for repo in report.repos
                if repo.error
            ],
            "scout_only_repos": [
                repo.repo
                for repo in report.repos
                if repo.enabled and not repo.worker_enabled
            ],
            "admitted": [item.to_dict() for item in report.admitted],
        },
    }
    if repo_health_reports is not None:
        digest["repo_health"] = {
            "repos_checked": len(repo_health_reports),
            "downgrade_count": len(
                [item for item in repo_health_reports if item.status == "downgrade"]
            ),
            "error_count": len(
                [item for item in repo_health_reports if item.status == "error"]
            ),
            "reports": [item.to_dict() for item in repo_health_reports],
        }
    if paid_platform_summary is not None:
        digest["paid_platforms"] = paid_platform_summary
    if pr_watch_summary is not None:
        digest["pr_watch"] = pr_watch_summary
    return digest


def admission_rejection_reason(
    issue: Issue,
    repo: RepoConfig,
    *,
    seen_sprint_ids: set[str] | None = None,
    worker_only: bool = False,
) -> str:
    seen_sprint_ids = seen_sprint_ids or set()
    if sprint_id(issue) in seen_sprint_ids:
        return "resolved_or_active_sprint"
    if (
        worker_only
        and repo.worker_issue_allow
        and issue.number not in repo.worker_issue_allow
    ):
        return "not_in_worker_issue_allowlist"
    if worker_only and issue.number in repo.worker_issue_deny:
        return "worker_issue_denylist"
    if issue.assignees:
        return "assigned"
    labels = {label.lower() for label in issue.labels}
    if labels.intersection(label.lower() for label in repo.labels_deny):
        return "denied_label"
    if repo.labels_allow and not labels.intersection(
        label.lower() for label in repo.labels_allow
    ):
        return "missing_allowed_label"
    lowered_title = issue.title.lower()
    denied_title_terms = [
        "dependabot",
        "dependencies",
        "deps",
        "release",
        "feature request",
        "enhancement",
        "enhancement request",
        "roadmap",
        "proposal",
        "testing setup",
        "initial test cases",
        "redesign",
        "ui/ux",
        "improved ui",
    ]
    if any(term in lowered_title for term in denied_title_terms):
        return "broad_or_nonproof_title"
    denied_title_prefixes = ["add ", "feat", "feature", "refactor", "chore", "docs"]
    if any(lowered_title.startswith(prefix) for prefix in denied_title_prefixes):
        return "broad_or_nonproof_title"
    return ""


def public_claim_reason(
    comments: list[IssueComment],
    github_actor: str = "",
) -> str:
    for comment in comments:
        body = comment.body.lower().replace("’", "'")
        author = comment.author.lower()
        if github_actor and author == github_actor.lower():
            continue
        if mentions_pull_request(comment.body):
            return "existing_pr_mentioned"
        if looks_claimed(body):
            return "claimed_by_comment"
    return ""


def open_pr_reason(
    pull_requests: list[PullRequest],
    github_actor: str = "",
) -> str:
    for pull_request in pull_requests:
        if github_actor and pull_request.author.lower() == github_actor.lower():
            return "existing_own_pr"
        return "existing_open_pr"
    return ""


def mentions_pull_request(text: str) -> bool:
    return bool(
        re.search(r"\bpr\s*#\d+\b", text, flags=re.IGNORECASE)
        or re.search(r"\bpull request\s*#?\d+\b", text, flags=re.IGNORECASE)
        or re.search(r"/pull/\d+\b", text, flags=re.IGNORECASE)
    )


def looks_claimed(body: str) -> bool:
    claimed_phrases = [
        "i'm working on",
        "i am working on",
        "working on this issue",
        "working on the issue",
        "please assign this issue to me",
        "currently investigating",
        "started tracing",
        "i'll take this",
        "i will take this",
        "i'd like to work on this",
        "id like to work on this",
        "i would like to work on this",
        "would like to work on this issue",
        "i'll align",
        "i will align",
        "submit a pr shortly",
        "submit a pull request",
        "opening a pr",
        "already implemented",
        "rebaseline and verify",
    ]
    return any(phrase in body for phrase in claimed_phrases)


def sprint_id(issue: Issue) -> str:
    return f"{issue.repo.replace('/', '-')}-{issue.number}"


def _seen_sprint_ids(state: ControllerState | None) -> set[str]:
    if state is None:
        return set()
    return {
        sprint.sprint_id for sprint in [*state.active_sprints, *state.completed_sprints]
    }
