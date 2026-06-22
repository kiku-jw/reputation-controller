"""Read-only repository health probes."""

from __future__ import annotations

import urllib.error
from dataclasses import dataclass, field
from urllib.parse import quote

from .http_json import HttpJsonClient


SELECTED_SCORECARD_CHECKS = [
    "Maintained",
    "CI-Tests",
    "Code-Review",
    "License",
    "Branch-Protection",
]


@dataclass(frozen=True)
class ScorecardCheck:
    name: str
    score: int
    reason: str
    documentation_url: str = ""
    details: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "score": self.score,
            "reason": self.reason,
            "documentation_url": self.documentation_url,
            "details": self.details,
        }


@dataclass(frozen=True)
class RepoHealthReport:
    repo: str
    status: str
    source_url: str
    score: float | None = None
    checked_at: str = ""
    commit: str = ""
    selected_checks: list[ScorecardCheck] = field(default_factory=list)
    advisory_reasons: list[str] = field(default_factory=list)
    error: str = ""

    def to_dict(self) -> dict:
        return {
            "repo": self.repo,
            "status": self.status,
            "source_url": self.source_url,
            "score": self.score,
            "checked_at": self.checked_at,
            "commit": self.commit,
            "selected_checks": [check.to_dict() for check in self.selected_checks],
            "advisory_reasons": self.advisory_reasons,
            "error": self.error,
        }


class ScorecardClient:
    def __init__(
        self,
        *,
        base_url: str = "https://api.scorecard.dev/projects/github.com",
        http: HttpJsonClient | None = None,
    ):
        self.base_url = base_url.rstrip("/")
        self.http = http or HttpJsonClient()

    def repo_health(self, repo: str) -> RepoHealthReport:
        source_url = scorecard_url(self.base_url, repo)
        try:
            raw = self.http.get_json(source_url)
        except urllib.error.HTTPError as exc:
            reason = (
                "scorecard_not_found" if exc.code == 404 else "scorecard_lookup_failed"
            )
            return RepoHealthReport(
                repo=repo,
                status="error",
                source_url=source_url,
                advisory_reasons=[reason],
                error=str(exc),
            )
        except Exception as exc:
            return RepoHealthReport(
                repo=repo,
                status="error",
                source_url=source_url,
                advisory_reasons=["scorecard_lookup_failed"],
                error=str(exc),
            )
        if not isinstance(raw, dict):
            return RepoHealthReport(
                repo=repo,
                status="error",
                source_url=source_url,
                advisory_reasons=["scorecard_invalid_payload"],
                error="Scorecard payload was not an object",
            )
        return repo_health_from_scorecard(repo, source_url, raw)


def scorecard_url(base_url: str, repo: str) -> str:
    return f"{base_url.rstrip('/')}/{quote(repo, safe='/')}"


def repo_health_from_scorecard(
    repo: str,
    source_url: str,
    payload: dict,
) -> RepoHealthReport:
    checks = [
        scorecard_check_from_dict(item)
        for item in payload.get("checks", [])
        if isinstance(item, dict)
    ]
    selected = [check for check in checks if check.name in SELECTED_SCORECARD_CHECKS]
    advisory_reasons = repo_health_advisory_reasons(selected)
    status = "downgrade" if advisory_reasons else "pass"
    repo_data = payload.get("repo", {})
    commit = ""
    if isinstance(repo_data, dict):
        commit = str(repo_data.get("commit", ""))
    score_raw = payload.get("score")
    score = float(score_raw) if isinstance(score_raw, int | float) else None
    return RepoHealthReport(
        repo=repo,
        status=status,
        source_url=source_url,
        score=score,
        checked_at=str(payload.get("date", "")),
        commit=commit,
        selected_checks=selected,
        advisory_reasons=advisory_reasons,
    )


def scorecard_check_from_dict(data: dict) -> ScorecardCheck:
    documentation = data.get("documentation", {})
    documentation_url = ""
    if isinstance(documentation, dict):
        documentation_url = str(documentation.get("url", ""))
    details_raw = data.get("details") or []
    details = [str(item) for item in details_raw if isinstance(item, str)]
    return ScorecardCheck(
        name=str(data.get("name", "")),
        score=int(data.get("score", -1)),
        reason=str(data.get("reason", "")),
        documentation_url=documentation_url,
        details=details,
    )


def repo_health_advisory_reasons(checks: list[ScorecardCheck]) -> list[str]:
    by_name = {check.name: check for check in checks}
    reasons: list[str] = []
    _append_low_score_reason(
        reasons,
        by_name,
        "Maintained",
        "low_maintained_score",
        minimum=5,
    )
    _append_low_score_reason(
        reasons,
        by_name,
        "CI-Tests",
        "weak_ci_tests",
        minimum=5,
    )
    _append_low_score_reason(
        reasons,
        by_name,
        "Code-Review",
        "weak_code_review",
        minimum=5,
    )
    _append_low_score_reason(
        reasons,
        by_name,
        "License",
        "missing_or_unrecognized_license",
        minimum=1,
    )
    _append_low_score_reason(
        reasons,
        by_name,
        "Branch-Protection",
        "weak_branch_protection",
        minimum=2,
    )
    return reasons


def build_repo_health_reports(
    repos: list[str],
    *,
    client: ScorecardClient | None = None,
) -> list[RepoHealthReport]:
    scorecard = client or ScorecardClient()
    return [scorecard.repo_health(repo) for repo in repos]


def _append_low_score_reason(
    reasons: list[str],
    by_name: dict[str, ScorecardCheck],
    check_name: str,
    reason: str,
    *,
    minimum: int,
) -> None:
    check = by_name.get(check_name)
    if check is None:
        return
    if check.score >= 0 and check.score < minimum:
        reasons.append(reason)
