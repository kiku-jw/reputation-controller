from reputation_controller.config import (
    ControllerConfig,
    LimitsConfig,
    PolicyConfig,
    RepoConfig,
    Secrets,
)
from reputation_controller.gates import check_public_action, check_wip_limits
from reputation_controller.state import ControllerState, Sprint


def make_config() -> ControllerConfig:
    return ControllerConfig(
        workspace="/tmp/oss-controller",
        state_dir=".controller/state",
        dry_run=True,
        github_actor="kiku-jw",
        secrets=Secrets(),
        limits=LimitsConfig(
            max_active_sprints=1,
            max_active_targets=3,
            max_open_hypotheses=5,
        ),
        policy=PolicyConfig(
            allow_public_comments=False,
            allow_pr_create=False,
            allow_force_push=False,
            forbidden_title_terms=["codex"],
        ),
        repos=[
            RepoConfig(
                name="fossasia/visdom",
                local_path="visdom",
                default_branch="dev",
                enabled=True,
            )
        ],
    )


def test_wip_gate_blocks_new_sprint_when_one_is_active():
    config = make_config()
    state = ControllerState(
        active_sprints=[
            Sprint(
                sprint_id="visdom-1197",
                repo="fossasia/visdom",
                issue_number=1197,
                title="Cypress E2E still failing",
                status="packet_created",
            )
        ]
    )

    decision = check_wip_limits(config, state)

    assert decision.allowed is False
    assert decision.code == "max_active_sprints"
    assert "visdom-1197" in decision.reason


def test_wip_gate_does_not_count_completed_target_history_as_active():
    config = make_config()
    state = ControllerState(
        target_history=[
            "fossasia/visdom",
            "Giskard-AI/giskard-oss",
            "fossasia/eventyay",
        ]
    )

    decision = check_wip_limits(config, state)

    assert decision.allowed is True


def test_wip_gate_blocks_when_active_sprints_reach_target_limit():
    config = make_config()
    config.limits = LimitsConfig(
        max_active_sprints=10,
        max_active_targets=2,
        max_open_hypotheses=5,
    )
    state = ControllerState(
        active_sprints=[
            Sprint(
                sprint_id="fossasia-visdom-1197",
                repo="fossasia/visdom",
                issue_number=1197,
                title="Cypress E2E still failing",
                status="packet_created",
            ),
            Sprint(
                sprint_id="fossasia-eventyay-3896",
                repo="fossasia/eventyay",
                issue_number=3896,
                title="UnboundLocalError in PDF Generation on Missing Assets",
                status="packet_created",
            ),
        ]
    )

    decision = check_wip_limits(config, state)

    assert decision.allowed is False
    assert decision.code == "max_active_targets"


def test_public_action_gate_blocks_disabled_pr_create_and_forbidden_title():
    config = make_config()

    disabled = check_public_action(
        config,
        action="create_pr",
        title="Stabilize Cypress env cleanup",
    )
    forbidden = check_public_action(
        config,
        action="create_pr",
        title="[codex] Stabilize Cypress env cleanup",
    )

    assert disabled.allowed is False
    assert disabled.code == "public_pr_create_disabled"
    assert forbidden.allowed is False
    assert forbidden.code == "forbidden_title_term"
