import datetime

from reputation_controller.config import ControllerConfig, PolicyConfig
from reputation_controller.public_actions import (
    PublicActionProposal,
    append_public_action_event,
    review_public_action,
)


def make_config(*, dry_run=True, mode="issue-comment") -> ControllerConfig:
    return ControllerConfig(
        workspace="/tmp/oss-controller",
        state_dir=".controller/state",
        dry_run=dry_run,
        policy=PolicyConfig(
            allow_public_comments=True,
            allow_pr_create=False,
            allow_force_push=False,
            public_action_mode=mode,
            public_pr_draft_only=True,
            public_action_cooldown_hours=24,
            forbidden_title_terms=["codex"],
        ),
    )


def test_review_allows_evidence_backed_issue_comment(tmp_path):
    proposal = PublicActionProposal(
        action="issue_comment",
        repo="fossasia/visdom",
        issue_number=1400,
        body="I reproduced this with a local websocket trace.",
        evidence=["raw/repro.log"],
    )

    review = review_public_action(
        make_config(),
        proposal,
        ledger_path=tmp_path / "public-actions.jsonl",
    )

    assert review.decision.allowed is True


def test_review_denies_comment_without_evidence(tmp_path):
    proposal = PublicActionProposal(
        action="issue_comment",
        repo="fossasia/visdom",
        issue_number=1400,
        body="I can work on this.",
    )

    review = review_public_action(
        make_config(),
        proposal,
        ledger_path=tmp_path / "public-actions.jsonl",
    )

    assert review.decision.allowed is False
    assert review.decision.code == "missing_evidence"


def test_review_denies_pr_when_mode_only_allows_comments(tmp_path):
    proposal = PublicActionProposal(
        action="create_pr",
        repo="fossasia/visdom",
        issue_number=1400,
        title="Fix compare live updates",
        body="Verification: pytest",
        branch="kiku-jw:fix/compare-live-updates",
        evidence=["raw/repro.log"],
        verification=["pytest"],
    )

    review = review_public_action(
        make_config(mode="issue-comment"),
        proposal,
        ledger_path=tmp_path / "public-actions.jsonl",
    )

    assert review.decision.allowed is False
    assert review.decision.code == "public_pr_mode_disabled"


def test_review_applies_repo_cooldown(tmp_path):
    ledger_path = tmp_path / "public-actions.jsonl"
    proposal = PublicActionProposal(
        action="issue_comment",
        repo="fossasia/visdom",
        issue_number=1400,
        body="Evidence-backed comment.",
        evidence=["raw/repro.log"],
    )
    decision = review_public_action(
        make_config(),
        proposal,
        ledger_path=ledger_path,
        now=datetime.datetime(2026, 6, 13, tzinfo=datetime.timezone.utc),
    ).decision
    append_public_action_event(
        ledger_path,
        proposal=proposal,
        decision=decision,
        status="performed",
        now=datetime.datetime(2026, 6, 13, tzinfo=datetime.timezone.utc),
    )

    second = review_public_action(
        make_config(),
        proposal,
        ledger_path=ledger_path,
        now=datetime.datetime(2026, 6, 13, 1, tzinfo=datetime.timezone.utc),
    )

    assert second.decision.allowed is False
    assert second.decision.code == "public_action_cooldown"
