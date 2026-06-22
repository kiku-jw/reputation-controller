from pathlib import Path

from reputation_controller.config import load_config
from reputation_controller.redaction import redact_text


def test_loads_json_config_and_env_without_leaking_secrets(tmp_path: Path):
    config_path = tmp_path / "controller.json"
    config_path.write_text(
        """
{
  "workspace": "/tmp/oss-controller",
  "state_dir": ".controller/state",
  "dry_run": true,
  "github_timeout_seconds": 12.5,
  "limits": {
    "max_active_sprints": 1,
    "max_active_targets": 3,
    "max_open_hypotheses": 5
  },
  "policy": {
    "allow_public_comments": false,
    "allow_pr_create": false,
    "allow_force_push": false,
    "public_action_mode": "none",
    "public_pr_draft_only": true,
    "public_action_cooldown_hours": 24,
    "max_open_controller_prs_per_repo": 1,
    "forbidden_title_terms": ["codex"]
  },
  "worker": {
    "allow_execution": false,
    "timeout_seconds": 1800
  },
  "paid_platforms": [
    {
      "name": "opire",
      "provider": "opire",
      "enabled": true,
      "endpoint_url": "https://api.opire.dev/rewards",
      "min_reward_cents": 10000,
      "max_trying_users": 3,
      "max_claimer_users": 0,
      "labels_deny": ["dependencies"],
      "languages_allow": ["Python"],
      "title_deny_terms": ["rewrite"]
    }
  ],
  "repos": [
    {
      "name": "fossasia/visdom",
      "local_path": "visdom",
      "default_branch": "dev",
      "enabled": true,
      "worker_enabled": false,
      "worker_issue_allow": [2499],
      "worker_issue_deny": [2523],
      "labels_allow": ["bug"],
      "labels_deny": ["dependencies"],
      "proof_commands": ["python3 -m pytest tests/test_bug.py -q"]
    }
  ]
}
""".strip()
    )
    env_path = tmp_path / ".env"
    env_path.write_text(
        "\n".join(
            [
                "GITHUB_TOKEN=fake-github-token",
                "GITHUB_ACTOR=operator",
                "LLM_API_KEY=fake-llm-key",
                "LLM_BASE_URL=https://api.openai.com/v1",
                "LLM_MODEL=ft:gpt-4.1-mini:test",
            ]
        )
    )

    config = load_config(config_path, env_path=env_path)

    assert config.workspace == Path("/tmp/oss-controller")
    assert config.dry_run is True
    assert config.github_timeout_seconds == 12.5
    assert config.github_actor == "operator"
    assert config.secrets.github_token == "fake-github-token"
    assert config.secrets.llm_api_key == "fake-llm-key"
    assert config.repos[0].name == "fossasia/visdom"
    assert config.repos[0].worker_enabled is False
    assert config.repos[0].worker_issue_allow == [2499]
    assert config.repos[0].worker_issue_deny == [2523]
    assert config.repos[0].proof_commands == ["python3 -m pytest tests/test_bug.py -q"]
    assert config.policy.forbidden_title_terms == ["codex"]
    assert config.policy.public_action_mode == "none"
    assert config.policy.public_pr_draft_only is True
    assert config.worker.allow_execution is False
    assert config.worker.timeout_seconds == 1800
    assert config.paid_platforms[0].name == "opire"
    assert config.paid_platforms[0].endpoint_url == "https://api.opire.dev/rewards"
    assert config.paid_platforms[0].min_reward_cents == 10000
    assert config.paid_platforms[0].languages_allow == ["Python"]
    assert config.limits.max_active_sprints == 1
    assert "fake-github-token" not in config.safe_summary()
    assert "fake-llm-key" not in config.safe_summary()
    assert redact_text(
        "token fake-github-token and fake-llm-key", config.secrets
    ) == ("token [REDACTED_GITHUB_TOKEN] and [REDACTED_LLM_API_KEY]")


def test_process_env_overrides_dotenv(tmp_path: Path):
    config_path = tmp_path / "controller.json"
    config_path.write_text(
        """
{
  "workspace": "/tmp/oss-controller",
  "state_dir": ".controller/state",
  "dry_run": true,
  "repos": []
}
""".strip()
    )
    env_path = tmp_path / ".env"
    env_path.write_text(
        "\n".join(
            [
                "CONTROLLER_DRY_RUN=true",
                "CONTROLLER_ALLOW_WORKER_EXECUTION=false",
                "CONTROLLER_GH_TIMEOUT_SECONDS=5",
            ]
        )
    )

    config = load_config(
        config_path,
        env_path=env_path,
        environ={
            "CONTROLLER_DRY_RUN": "false",
            "CONTROLLER_ALLOW_WORKER_EXECUTION": "true",
            "CONTROLLER_GH_TIMEOUT_SECONDS": "9",
        },
    )

    assert config.dry_run is False
    assert config.worker.allow_execution is True
    assert config.github_timeout_seconds == 9
