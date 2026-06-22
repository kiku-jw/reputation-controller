"""CI check classification."""

from __future__ import annotations

from dataclasses import dataclass, field

from .github import CheckRun


@dataclass
class CIVerdict:
    status: str
    actionable_failures: list[str] = field(default_factory=list)
    pending: list[str] = field(default_factory=list)
    external_skips: list[str] = field(default_factory=list)


def classify_checks(checks: list[CheckRun]) -> CIVerdict:
    actionable_failures: list[str] = []
    pending: list[str] = []
    external_skips: list[str] = []

    for check in checks:
        state = check.state.lower()
        if state in {"pass", "success"}:
            continue
        if state in {"pending", "queued", "in_progress"}:
            pending.append(check.name)
            continue
        if _is_external_skip(check):
            external_skips.append(check.name)
            continue
        if state in {"fail", "failure", "error", "cancelled", "timed_out"}:
            actionable_failures.append(check.name)

    if actionable_failures:
        status = "fail"
    elif pending:
        status = "pending"
    else:
        status = "pass"
    return CIVerdict(
        status=status,
        actionable_failures=actionable_failures,
        pending=pending,
        external_skips=external_skips,
    )


def _is_external_skip(check: CheckRun) -> bool:
    return check.state.lower() in {"skip", "skipped", "skipping"} and (
        "sourcery" in check.name.lower() or "sourcery.ai" in check.link.lower()
    )
