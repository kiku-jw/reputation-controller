"""Decision loop for proof-first OSS reputation work."""

from __future__ import annotations

import datetime
import json
from dataclasses import dataclass
from pathlib import Path

from .config import ControllerConfig, RepoConfig
from .gates import check_wip_limits
from .github import GitHubClient, Issue, IssueComment
from .public_actions import (
    PublicActionProposal,
    append_public_action_event,
    review_public_action,
)
from .runner import WorkerResult, WorkerSpec, prepare_repo_checkout, run_worker
from .scout import (
    admission_rejection_reason,
    build_scout_report,
    first_worker_candidate,
    public_claim_reason,
    scout_diagnostics,
    sprint_id,
)
from .state import ControllerState, Sprint, StateStore


@dataclass
class RunResult:
    status: str
    message: str
    packet_path: Path | None = None
    gate_code: str = ""
    public_actions: list[str] | None = None
    diagnostics: dict | None = None


class ReputationController:
    def __init__(
        self,
        config: ControllerConfig,
        github: GitHubClient,
        state_store: StateStore,
    ):
        self.config = config
        self.github = github
        self.state_store = state_store

    def run_once(self) -> RunResult:
        state = self.state_store.load()
        if state.active_sprints:
            result = self._process_active_sprint(state, state.active_sprints[0])
            self.state_store.save(state)
            return result

        gate = check_wip_limits(self.config, state)
        if not gate.allowed:
            _append_event(state, "blocked_by_gate", gate.reason)
            self.state_store.save(state)
            return RunResult(
                status="blocked_by_gate",
                message=gate.reason,
                gate_code=gate.code,
                public_actions=[],
            )

        candidate, diagnostics = self._select_candidate(state)
        if candidate is None:
            _append_event(
                state,
                "no_candidate",
                json.dumps(diagnostics, sort_keys=True),
            )
            self.state_store.save(state)
            return RunResult(
                status="no_candidate",
                message="No admitted issue candidate found",
                public_actions=[],
                diagnostics=diagnostics,
            )

        sprint = Sprint(
            sprint_id=_sprint_id(candidate),
            repo=candidate.repo,
            issue_number=candidate.number,
            title=candidate.title,
            status="packet_created",
        )
        packet_path = self._write_packet(candidate)
        state.active_sprints.append(sprint)
        if candidate.repo not in state.target_history:
            state.target_history.append(candidate.repo)
        _append_event(state, "packet_created", str(packet_path))
        self.state_store.save(state)
        return RunResult(
            status="packet_created",
            message=f"Created task packet for {candidate.repo}#{candidate.number}",
            packet_path=packet_path,
            public_actions=[],
        )

    def _process_active_sprint(
        self,
        state: ControllerState,
        sprint: Sprint,
    ) -> RunResult:
        evidence_dir = self.config.evidence_dir / sprint.sprint_id
        result_path = evidence_dir / "worker-result.json"
        if result_path.exists():
            worker_result = WorkerResult.from_file(result_path)
            return self._handle_worker_result(state, sprint, worker_result, result_path)

        if not self.config.worker.allow_execution:
            message = f"Active sprint limit reached: {sprint.sprint_id}"
            _append_event(state, "blocked_by_gate", message)
            return RunResult(
                status="blocked_by_gate",
                message=message,
                gate_code="max_active_sprints",
                public_actions=[],
            )

        repo = self._repo_config(sprint.repo)
        if repo is None:
            _resolve_sprint(state, sprint.sprint_id, "needs-human")
            return RunResult(
                status="needs-human",
                message=f"Repo config not found for {sprint.repo}",
                public_actions=[],
            )
        if not repo.worker_enabled:
            _resolve_sprint(state, sprint.sprint_id, "needs-human")
            return RunResult(
                status="needs-human",
                message=f"Worker execution disabled for {sprint.repo}",
                gate_code="repo_worker_disabled",
                public_actions=[],
            )

        evidence_dir.mkdir(parents=True, exist_ok=True)
        repo_path = self.config.workspace / repo.local_path
        try:
            prepare_output = prepare_repo_checkout(
                repo_path,
                default_branch=repo.default_branch,
            )
        except Exception:
            _append_event(
                state,
                "repo_prepare_failed",
                sprint.sprint_id,
            )
            return RunResult(
                status="repo_prepare_failed",
                message=f"Could not prepare repo checkout for {sprint.sprint_id}",
                public_actions=[],
            )
        (evidence_dir / "repo-prepare.log").write_text("\n".join(prepare_output) + "\n")

        packet_path = self.config.tasks_dir / f"{sprint.sprint_id}.md"
        spec = WorkerSpec(
            repo_path=repo_path,
            packet_path=packet_path,
            evidence_dir=evidence_dir,
            result_path=result_path,
            model=self.config.llm_reasoning_model or self.config.llm_model,
            timeout_seconds=self.config.worker.timeout_seconds,
        )
        completed = run_worker(spec)
        evidence_dir.mkdir(parents=True, exist_ok=True)
        (evidence_dir / "worker-stdout.log").write_text(completed.stdout)
        (evidence_dir / "worker-stderr.log").write_text(completed.stderr)
        if completed.returncode != 0:
            _append_event(
                state,
                "worker_failed",
                f"{sprint.sprint_id} exit={completed.returncode}",
            )
            return RunResult(
                status="worker_failed",
                message=f"Worker failed for {sprint.sprint_id}",
                public_actions=[],
            )
        if not result_path.exists():
            _append_event(state, "worker_result_missing", str(result_path))
            return RunResult(
                status="needs_worker_result",
                message=f"Worker did not write {result_path}",
                public_actions=[],
            )

        worker_result = WorkerResult.from_file(result_path)
        return self._handle_worker_result(state, sprint, worker_result, result_path)

    def _handle_worker_result(
        self,
        state: ControllerState,
        sprint: Sprint,
        worker_result: WorkerResult,
        result_path: Path,
    ) -> RunResult:
        verdict = worker_result.verdict
        if verdict not in {"proof", "kill", "needs-human"}:
            _append_event(state, "worker_bad_verdict", verdict)
            return RunResult(
                status="needs-human",
                message=f"Unsupported worker verdict: {verdict}",
                public_actions=[],
            )

        public_actions: list[str] = []
        if verdict == "proof" and worker_result.public_action_proposal is not None:
            public_actions = self._review_and_maybe_apply_public_action(
                worker_result.public_action_proposal
            )

        _resolve_sprint(state, sprint.sprint_id, verdict)
        _append_event(
            state,
            f"sprint_{verdict}",
            f"{sprint.sprint_id} result={result_path}",
        )
        return RunResult(
            status=verdict,
            message=worker_result.summary or f"Worker verdict: {verdict}",
            public_actions=public_actions,
        )

    def _review_and_maybe_apply_public_action(
        self,
        proposal: PublicActionProposal,
    ) -> list[str]:
        review = review_public_action(
            self.config,
            proposal,
            ledger_path=self.config.public_actions_path,
        )
        if not review.decision.allowed:
            append_public_action_event(
                self.config.public_actions_path,
                proposal=proposal,
                decision=review.decision,
                status="denied",
                secrets=self.config.secrets,
            )
            return [f"denied:{review.decision.code}"]

        if self.config.dry_run:
            append_public_action_event(
                self.config.public_actions_path,
                proposal=proposal,
                decision=review.decision,
                status="dry-run",
                secrets=self.config.secrets,
            )
            return [f"dry-run:{proposal.action}"]

        url = self._perform_public_action(proposal)
        append_public_action_event(
            self.config.public_actions_path,
            proposal=proposal,
            decision=review.decision,
            status="performed",
            url=url,
            secrets=self.config.secrets,
        )
        return [f"performed:{proposal.action}:{url}"]

    def _perform_public_action(self, proposal: PublicActionProposal) -> str:
        if proposal.action == "issue_comment":
            return self.github.comment_issue(
                proposal.repo,
                proposal.issue_number,
                proposal.body,
            )
        if proposal.action == "create_pr":
            repo = self._repo_config(proposal.repo)
            base = repo.default_branch if repo is not None else "main"
            head = proposal.branch
            if ":" not in head and self.config.github_actor:
                head = f"{self.config.github_actor}:{head}"
            return self.github.create_pr(
                proposal.repo,
                title=proposal.title,
                body=proposal.body,
                base=base,
                head=head,
                draft=proposal.draft,
            )
        raise ValueError(f"Unsupported public action: {proposal.action}")

    def _select_candidate(self, state: ControllerState) -> tuple[Issue | None, dict]:
        report = build_scout_report(
            self.config,
            self.github,
            state,
            worker_only=True,
        )
        for item in report.rejected:
            if item.reason in {"existing_pr_mentioned", "claimed_by_comment"}:
                _append_event(
                    state,
                    "candidate_skipped",
                    f"{sprint_id(item.issue)} {item.reason}",
                )
        return first_worker_candidate(report), scout_diagnostics(report)

    def _repo_config(self, repo_name: str) -> RepoConfig | None:
        for repo in self.config.repos:
            if repo.name == repo_name:
                return repo
        return None

    def _write_packet(self, issue: Issue) -> Path:
        self.config.tasks_dir.mkdir(parents=True, exist_ok=True)
        path = self.config.tasks_dir / f"{_sprint_id(issue)}.md"
        path.write_text(_packet_text(issue, self.config))
        return path


def _issue_admitted(issue: Issue, repo: RepoConfig) -> bool:
    return admission_rejection_reason(issue, repo) == ""


def _public_claim_reason(
    comments: list[IssueComment],
    github_actor: str = "",
) -> str:
    return public_claim_reason(comments, github_actor)


def _sprint_id(issue: Issue) -> str:
    return sprint_id(issue)


def _packet_text(issue: Issue, config: ControllerConfig) -> str:
    created_at = (
        datetime.datetime.now(datetime.timezone.utc).replace(microsecond=0).isoformat()
    )
    return f"""# OSS Reputation Sprint Packet: {issue.repo}#{issue.number}

Created: {created_at}
Dry run: {str(config.dry_run).lower()}

## Target

- Repo: `{issue.repo}`
- Issue: `{issue.title}`
- URL: {issue.url}

## Goal

Produce a narrow, maintainer-grade contribution only if there is local proof.

## Required Evidence

- Exact failing command or issue reproduction.
- Narrow root cause tied to files/symbols.
- Minimal patch or a proof comment that moves the issue forward.
- Verification command output.

## Forbidden actions

- Open a PR without local proof.
- Open a PR with `codex` or generated-looking wording in the title.
- Post public comments while `CONTROLLER_ALLOW_PUBLIC_COMMENTS=false`.
- Create PRs while `CONTROLLER_ALLOW_PR_CREATE=false`.
- Force-push while `CONTROLLER_ALLOW_FORCE_PUSH=false`.
- Race assigned issues, active PRs, dependency-only work, or broad refactors.

## Worker Contract

1. Read repo instructions before edits.
2. Keep scope to the issue.
3. Stop if the issue is ambiguous or cannot be reproduced.
4. Store evidence under `.controller/evidence/{_sprint_id(issue)}/`.
5. Return a concise verdict: `proof`, `kill`, or `needs-human`.
"""


def _append_event(state: ControllerState, event_type: str, message: str) -> None:
    state.events.append(
        {
            "at": (
                datetime.datetime.now(datetime.timezone.utc)
                .replace(microsecond=0)
                .isoformat()
            ),
            "type": event_type,
            "message": message,
        }
    )


def _resolve_sprint(state: ControllerState, sprint_id: str, status: str) -> bool:
    for index, sprint in enumerate(state.active_sprints):
        if sprint.sprint_id == sprint_id:
            resolved = Sprint(
                sprint_id=sprint.sprint_id,
                repo=sprint.repo,
                issue_number=sprint.issue_number,
                title=sprint.title,
                status=status,
            )
            del state.active_sprints[index]
            state.completed_sprints.append(resolved)
            return True
    return False
