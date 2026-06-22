"""Safety gates for autonomous OSS work."""

from __future__ import annotations

from dataclasses import dataclass

from .config import ControllerConfig
from .state import ControllerState


@dataclass(frozen=True)
class GateDecision:
    allowed: bool
    code: str
    reason: str


def allow(reason: str = "allowed") -> GateDecision:
    return GateDecision(allowed=True, code="allowed", reason=reason)


def deny(code: str, reason: str) -> GateDecision:
    return GateDecision(allowed=False, code=code, reason=reason)


def check_wip_limits(config: ControllerConfig, state: ControllerState) -> GateDecision:
    if len(state.active_sprints) >= config.limits.max_active_sprints:
        active = ", ".join(sprint.sprint_id for sprint in state.active_sprints)
        return deny("max_active_sprints", f"Active sprint limit reached: {active}")
    active_targets = {sprint.repo for sprint in state.active_sprints}
    if len(active_targets) >= config.limits.max_active_targets:
        return deny("max_active_targets", "Target limit reached for current window")
    if len(state.open_hypotheses) >= config.limits.max_open_hypotheses:
        return deny("max_open_hypotheses", "Open hypothesis limit reached")
    return allow()


def check_public_action(
    config: ControllerConfig,
    *,
    action: str,
    title: str = "",
) -> GateDecision:
    lowered_title = title.lower()
    for term in config.policy.forbidden_title_terms:
        if term.lower() in lowered_title:
            return deny(
                "forbidden_title_term", f"Title contains forbidden term: {term}"
            )
    if action == "create_pr" and not config.policy.allow_pr_create:
        return deny("public_pr_create_disabled", "PR creation is disabled")
    if action == "comment" and not config.policy.allow_public_comments:
        return deny("public_comments_disabled", "Public comments are disabled")
    if action == "force_push" and not config.policy.allow_force_push:
        return deny("force_push_disabled", "Force-push is disabled")
    return allow()
