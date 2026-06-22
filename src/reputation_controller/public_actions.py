"""Public action policy and ledger."""

from __future__ import annotations

import datetime
import json
from dataclasses import dataclass, field
from pathlib import Path

from .config import ControllerConfig
from .gates import GateDecision, allow, deny
from .redaction import redact_text


MODE_ORDER = {
    "none": 0,
    "issue-comment": 1,
    "draft-pr": 2,
    "pr": 3,
}


@dataclass(frozen=True)
class PublicActionProposal:
    action: str
    repo: str
    issue_number: int
    body: str
    title: str = ""
    branch: str = ""
    draft: bool = True
    evidence: list[str] = field(default_factory=list)
    verification: list[str] = field(default_factory=list)

    @classmethod
    def from_dict(cls, data: dict) -> "PublicActionProposal":
        action = str(data.get("action", ""))
        if action == "open_pr":
            action = "create_pr"
        if action == "comment":
            action = "issue_comment"
        return cls(
            action=action,
            repo=str(data.get("repo", "")),
            issue_number=int(data.get("issue_number", 0)),
            body=str(data.get("body", "")),
            title=str(data.get("title", "")),
            branch=str(data.get("branch", "")),
            draft=bool(data.get("draft", True)),
            evidence=[str(item) for item in data.get("evidence", [])],
            verification=[str(item) for item in data.get("verification", [])],
        )

    def to_dict(self) -> dict:
        return {
            "action": self.action,
            "repo": self.repo,
            "issue_number": self.issue_number,
            "body": self.body,
            "title": self.title,
            "branch": self.branch,
            "draft": self.draft,
            "evidence": self.evidence,
            "verification": self.verification,
        }


@dataclass(frozen=True)
class PublicActionReview:
    proposal: PublicActionProposal
    decision: GateDecision

    def to_dict(self) -> dict:
        return {
            "proposal": self.proposal.to_dict(),
            "decision": self.decision.__dict__,
        }


def review_public_action(
    config: ControllerConfig,
    proposal: PublicActionProposal,
    *,
    ledger_path: Path | None = None,
    now: datetime.datetime | None = None,
) -> PublicActionReview:
    decision = _check_policy(config, proposal)
    if decision.allowed and ledger_path is not None:
        decision = _check_cooldown(config, proposal, ledger_path, now=now)
    return PublicActionReview(proposal=proposal, decision=decision)


def append_public_action_event(
    path: Path,
    *,
    proposal: PublicActionProposal,
    decision: GateDecision,
    status: str,
    url: str = "",
    secrets=None,
    now: datetime.datetime | None = None,
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    event = {
        "at": _iso(now),
        "repo": proposal.repo,
        "issue_number": proposal.issue_number,
        "action": proposal.action,
        "status": status,
        "decision_code": decision.code,
        "decision_allowed": decision.allowed,
        "title": proposal.title,
        "url": url,
    }
    text = json.dumps(event, sort_keys=True)
    if secrets is not None:
        text = redact_text(text, secrets)
    handle = path.open("a")
    try:
        handle.write(text + "\n")
    finally:
        handle.close()


def load_public_action_events(path: Path) -> list[dict]:
    if not path.exists():
        return []
    events: list[dict] = []
    for line in path.read_text().splitlines():
        if line.strip():
            events.append(json.loads(line))
    return events


def _check_policy(
    config: ControllerConfig,
    proposal: PublicActionProposal,
) -> GateDecision:
    mode = config.policy.public_action_mode
    if mode not in MODE_ORDER:
        return deny("invalid_public_action_mode", f"Unknown public mode: {mode}")
    if mode == "none":
        return deny("public_action_mode_none", "Public action mode is none")

    lowered_title = proposal.title.lower()
    for term in config.policy.forbidden_title_terms:
        if term.lower() in lowered_title:
            return deny(
                "forbidden_title_term", f"Title contains forbidden term: {term}"
            )

    if proposal.action == "issue_comment":
        if MODE_ORDER[mode] < MODE_ORDER["issue-comment"]:
            return deny(
                "public_comment_mode_disabled", "Issue comments are not enabled"
            )
        if not config.policy.allow_public_comments:
            return deny("public_comments_disabled", "Public comments are disabled")
        if not proposal.body.strip():
            return deny("missing_comment_body", "Issue comment body is empty")
        if not proposal.evidence:
            return deny("missing_evidence", "Public comment requires evidence")
        return allow("issue comment allowed")

    if proposal.action == "create_pr":
        if MODE_ORDER[mode] < MODE_ORDER["draft-pr"]:
            return deny("public_pr_mode_disabled", "PR mode is not enabled")
        if not config.policy.allow_pr_create:
            return deny("public_pr_create_disabled", "PR creation is disabled")
        if config.policy.public_pr_draft_only and not proposal.draft:
            return deny("draft_pr_required", "Only draft PRs are enabled")
        if not proposal.title.strip():
            return deny("missing_pr_title", "PR title is empty")
        if not proposal.branch.strip():
            return deny("missing_pr_branch", "PR branch is empty")
        if not proposal.evidence:
            return deny("missing_evidence", "PR creation requires evidence")
        if not proposal.verification:
            return deny("missing_verification", "PR creation requires verification")
        return allow("PR creation allowed")

    if proposal.action == "force_push":
        if not config.policy.allow_force_push:
            return deny("force_push_disabled", "Force-push is disabled")
        return allow("force-push allowed")

    return deny("unknown_public_action", f"Unknown public action: {proposal.action}")


def _check_cooldown(
    config: ControllerConfig,
    proposal: PublicActionProposal,
    ledger_path: Path,
    *,
    now: datetime.datetime | None,
) -> GateDecision:
    hours = config.policy.public_action_cooldown_hours
    if hours <= 0:
        return allow("cooldown disabled")

    current = now or datetime.datetime.now(datetime.timezone.utc)
    cutoff = current - datetime.timedelta(hours=hours)
    for event in reversed(load_public_action_events(ledger_path)):
        if event.get("repo") != proposal.repo:
            continue
        if event.get("status") != "performed":
            continue
        event_time = _parse_time(str(event.get("at", "")))
        if event_time is not None and event_time > cutoff:
            return deny(
                "public_action_cooldown",
                f"Public action cooldown active for {proposal.repo}",
            )
    return allow("cooldown clear")


def _parse_time(value: str) -> datetime.datetime | None:
    try:
        parsed = datetime.datetime.fromisoformat(value)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=datetime.timezone.utc)
    return parsed


def _iso(now: datetime.datetime | None) -> str:
    value = now or datetime.datetime.now(datetime.timezone.utc)
    return value.replace(microsecond=0).isoformat()
