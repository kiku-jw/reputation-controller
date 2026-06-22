"""Configuration loading for the OSS reputation controller."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Mapping

from .redaction import redact_mapping, redact_text


@dataclass
class Secrets:
    github_token: str = ""
    llm_api_key: str = ""

    def present(self) -> dict[str, bool]:
        return {
            "github_token": bool(self.github_token),
            "llm_api_key": bool(self.llm_api_key),
        }


@dataclass
class LimitsConfig:
    max_active_sprints: int = 1
    max_active_targets: int = 3
    max_open_hypotheses: int = 5


@dataclass
class PolicyConfig:
    allow_public_comments: bool = False
    allow_pr_create: bool = False
    allow_force_push: bool = False
    public_action_mode: str = "none"
    public_pr_draft_only: bool = True
    public_action_cooldown_hours: int = 24
    max_open_controller_prs_per_repo: int = 1
    forbidden_title_terms: list[str] = field(default_factory=lambda: ["codex"])


@dataclass
class WorkerConfig:
    allow_execution: bool = False
    timeout_seconds: int = 1800


@dataclass
class RepoConfig:
    name: str
    local_path: str
    default_branch: str
    enabled: bool = True
    worker_enabled: bool = True
    worker_issue_allow: list[int] = field(default_factory=list)
    worker_issue_deny: list[int] = field(default_factory=list)
    labels_allow: list[str] = field(default_factory=list)
    labels_deny: list[str] = field(default_factory=list)
    proof_commands: list[str] = field(default_factory=list)


@dataclass
class PaidPlatformConfig:
    name: str
    provider: str
    enabled: bool = True
    endpoint_url: str = ""
    min_reward_cents: int = 10000
    max_trying_users: int = 3
    max_claimer_users: int = 0
    labels_deny: list[str] = field(default_factory=list)
    languages_allow: list[str] = field(default_factory=list)
    title_deny_terms: list[str] = field(default_factory=list)


@dataclass
class ControllerConfig:
    workspace: Path | str
    state_dir: Path | str
    dry_run: bool
    github_actor: str = ""
    github_timeout_seconds: float = 30
    secrets: Secrets = field(default_factory=Secrets)
    limits: LimitsConfig = field(default_factory=LimitsConfig)
    policy: PolicyConfig = field(default_factory=PolicyConfig)
    worker: WorkerConfig = field(default_factory=WorkerConfig)
    repos: list[RepoConfig] = field(default_factory=list)
    paid_platforms: list[PaidPlatformConfig] = field(default_factory=list)
    llm_base_url: str = "https://api.openai.com/v1"
    llm_model: str = ""
    llm_small_model: str = ""
    llm_reasoning_model: str = ""

    def __post_init__(self) -> None:
        self.workspace = Path(self.workspace)
        self.state_dir = Path(self.state_dir)

    @property
    def state_path(self) -> Path:
        return self.workspace / self.state_dir / "state.json"

    @property
    def tasks_dir(self) -> Path:
        return self.workspace / self.state_dir.parent / "tasks"

    @property
    def evidence_dir(self) -> Path:
        return self.workspace / self.state_dir.parent / "evidence"

    @property
    def public_actions_path(self) -> Path:
        return self.workspace / self.state_dir.parent / "public-actions.jsonl"

    def safe_summary(self) -> str:
        data = {
            "workspace": str(self.workspace),
            "state_dir": str(self.state_dir),
            "dry_run": self.dry_run,
            "github_actor": self.github_actor,
            "github_timeout_seconds": self.github_timeout_seconds,
            "secrets_present": self.secrets.present(),
            "limits": self.limits.__dict__,
            "policy": self.policy.__dict__,
            "worker": self.worker.__dict__,
            "repos": [repo.__dict__ for repo in self.repos],
            "paid_platforms": [platform.__dict__ for platform in self.paid_platforms],
            "llm_base_url": self.llm_base_url,
            "llm_model": self.llm_model,
            "llm_small_model": self.llm_small_model,
            "llm_reasoning_model": self.llm_reasoning_model,
        }
        return redact_text(json.dumps(data, indent=2, sort_keys=True), self.secrets)


def load_config(
    config_path: Path | str,
    *,
    env_path: Path | str | None = None,
    environ: Mapping[str, str] | None = None,
) -> ControllerConfig:
    path = Path(config_path)
    data = json.loads(path.read_text())
    env = {}
    if env_path is not None and Path(env_path).exists():
        env.update(parse_dotenv(Path(env_path).read_text()))
    env.update(os.environ if environ is None else environ)

    secrets = Secrets(
        github_token=env.get("GITHUB_TOKEN", ""),
        llm_api_key=env.get("LLM_API_KEY", ""),
    )

    limits_raw = data.get("limits", {})
    policy_raw = data.get("policy", {})
    repos_raw = data.get("repos", [])
    paid_platforms_raw = data.get("paid_platforms", [])

    config = ControllerConfig(
        workspace=env.get("CONTROLLER_WORKSPACE", data.get("workspace", ".")),
        state_dir=env.get(
            "CONTROLLER_STATE_DIR",
            data.get("state_dir", ".controller/state"),
        ),
        dry_run=_env_bool(env, "CONTROLLER_DRY_RUN", bool(data.get("dry_run", True))),
        github_actor=env.get("GITHUB_ACTOR", data.get("github_actor", "")),
        github_timeout_seconds=float(
            env.get(
                "CONTROLLER_GH_TIMEOUT_SECONDS",
                data.get("github_timeout_seconds", 30),
            )
        ),
        secrets=secrets,
        limits=LimitsConfig(
            max_active_sprints=int(
                env.get(
                    "CONTROLLER_MAX_ACTIVE_SPRINTS",
                    limits_raw.get("max_active_sprints", 1),
                )
            ),
            max_active_targets=int(
                env.get(
                    "CONTROLLER_MAX_ACTIVE_TARGETS",
                    limits_raw.get("max_active_targets", 3),
                )
            ),
            max_open_hypotheses=int(
                env.get(
                    "CONTROLLER_MAX_OPEN_HYPOTHESES",
                    limits_raw.get("max_open_hypotheses", 5),
                )
            ),
        ),
        policy=PolicyConfig(
            allow_public_comments=_env_bool(
                env,
                "CONTROLLER_ALLOW_PUBLIC_COMMENTS",
                bool(policy_raw.get("allow_public_comments", False)),
            ),
            allow_pr_create=_env_bool(
                env,
                "CONTROLLER_ALLOW_PR_CREATE",
                bool(policy_raw.get("allow_pr_create", False)),
            ),
            allow_force_push=_env_bool(
                env,
                "CONTROLLER_ALLOW_FORCE_PUSH",
                bool(policy_raw.get("allow_force_push", False)),
            ),
            public_action_mode=env.get(
                "CONTROLLER_PUBLIC_ACTION_MODE",
                policy_raw.get("public_action_mode", "none"),
            ),
            public_pr_draft_only=_env_bool(
                env,
                "CONTROLLER_PUBLIC_PR_DRAFT_ONLY",
                bool(policy_raw.get("public_pr_draft_only", True)),
            ),
            public_action_cooldown_hours=int(
                env.get(
                    "CONTROLLER_PUBLIC_ACTION_COOLDOWN_HOURS",
                    policy_raw.get("public_action_cooldown_hours", 24),
                )
            ),
            max_open_controller_prs_per_repo=int(
                env.get(
                    "CONTROLLER_MAX_OPEN_CONTROLLER_PRS_PER_REPO",
                    policy_raw.get("max_open_controller_prs_per_repo", 1),
                )
            ),
            forbidden_title_terms=list(
                policy_raw.get("forbidden_title_terms", ["codex"])
            ),
        ),
        worker=WorkerConfig(
            allow_execution=_env_bool(
                env,
                "CONTROLLER_ALLOW_WORKER_EXECUTION",
                bool(data.get("worker", {}).get("allow_execution", False)),
            ),
            timeout_seconds=int(
                env.get(
                    "CONTROLLER_WORKER_TIMEOUT_SECONDS",
                    data.get("worker", {}).get("timeout_seconds", 1800),
                )
            ),
        ),
        repos=[_repo_from_dict(repo) for repo in repos_raw],
        paid_platforms=[
            _paid_platform_from_dict(platform) for platform in paid_platforms_raw
        ],
        llm_base_url=env.get("LLM_BASE_URL", data.get("llm_base_url", "")),
        llm_model=env.get("LLM_MODEL", data.get("llm_model", "")),
        llm_small_model=env.get("LLM_SMALL_MODEL", data.get("llm_small_model", "")),
        llm_reasoning_model=env.get(
            "LLM_REASONING_MODEL",
            data.get("llm_reasoning_model", ""),
        ),
    )
    redact_mapping(env, secrets)
    return config


def parse_dotenv(text: str) -> dict[str, str]:
    values: dict[str, str] = {}
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip().strip('"').strip("'")
    return values


def _repo_from_dict(data: dict) -> RepoConfig:
    enabled = bool(data.get("enabled", True))
    return RepoConfig(
        name=data["name"],
        local_path=data.get("local_path", data["name"].split("/")[-1]),
        default_branch=data.get("default_branch", "main"),
        enabled=enabled,
        worker_enabled=bool(data.get("worker_enabled", enabled)),
        worker_issue_allow=[int(item) for item in data.get("worker_issue_allow", [])],
        worker_issue_deny=[int(item) for item in data.get("worker_issue_deny", [])],
        labels_allow=list(data.get("labels_allow", [])),
        labels_deny=list(data.get("labels_deny", [])),
        proof_commands=list(data.get("proof_commands", [])),
    )


def _paid_platform_from_dict(data: dict) -> PaidPlatformConfig:
    return PaidPlatformConfig(
        name=data["name"],
        provider=data.get("provider", data["name"]),
        enabled=bool(data.get("enabled", True)),
        endpoint_url=data.get("endpoint_url", ""),
        min_reward_cents=int(data.get("min_reward_cents", 10000)),
        max_trying_users=int(data.get("max_trying_users", 3)),
        max_claimer_users=int(data.get("max_claimer_users", 0)),
        labels_deny=list(data.get("labels_deny", [])),
        languages_allow=list(data.get("languages_allow", [])),
        title_deny_terms=list(data.get("title_deny_terms", [])),
    )


def _env_bool(env: Mapping[str, str], name: str, default: bool) -> bool:
    value = env.get(name)
    if value is None or value == "":
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}
