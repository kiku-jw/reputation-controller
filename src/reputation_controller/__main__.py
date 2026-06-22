"""Command-line entrypoint."""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

from .ci import classify_checks
from .config import load_config
from .controller import ReputationController
from .experiments import StructuralProbeSpec
from .experiments import build_context_probe_experiment
from .github import GitHubClient
from .paid_platforms import build_paid_platform_report
from .pr_watch import read_pr_watch_summary
from .public_actions import review_public_action
from .repo_health import ScorecardClient, build_repo_health_reports
from .runner import WorkerResult
from .scout import build_digest, build_scout_report
from .state import StateStore
from .target_admission import build_target_admission_report
from .workflow_preflight import build_workflow_preflight_report


def main() -> int:
    parser = argparse.ArgumentParser(prog="reputation-controller")
    parser.add_argument(
        "--config",
        default="config/controller.example.json",
        help="Path to controller JSON config",
    )
    parser.add_argument("--env", default=".env", help="Optional dotenv path")
    subcommands = parser.add_subparsers(dest="command", required=True)

    subcommands.add_parser("validate", help="Load config and print safe summary")
    subcommands.add_parser("status", help="Print controller state")
    resolve = subcommands.add_parser("resolve", help="Resolve an active sprint")
    resolve.add_argument("--sprint-id", required=True)
    resolve.add_argument(
        "--status",
        choices=["proof", "kill", "needs-human", "merged"],
        required=True,
    )
    scan = subcommands.add_parser("scan", help="Print open issues from enabled repos")
    scan.add_argument("--limit", type=int, default=30)
    scout = subcommands.add_parser(
        "scout",
        help="Read-only candidate scout with admission/rejection reasons",
    )
    scout.add_argument("--limit", type=int, default=30)
    scout.add_argument(
        "--worker-only",
        action="store_true",
        help="Only scan repos eligible for worker execution",
    )
    platform_scout = subcommands.add_parser(
        "platform-scout",
        help="Read-only paid-platform scout; never creates worker packets",
    )
    platform_scout.add_argument("--limit", type=int, default=30)
    repo_health = subcommands.add_parser(
        "repo-health",
        help="Read-only OpenSSF Scorecard repo health probe",
    )
    repo_health.add_argument("--repo", required=True)
    workflow_preflight = subcommands.add_parser(
        "workflow-preflight",
        help="Review-only local workflow validation via wrkflw when installed",
    )
    workflow_preflight.add_argument("--repo", required=True)
    workflow_preflight.add_argument("--tool", default="wrkflw")
    target_admission = subcommands.add_parser(
        "target-admission",
        help="Read-only worker-readiness probe for one configured repo",
    )
    target_admission.add_argument("--repo", required=True)
    target_admission.add_argument("--workflow-tool", default="wrkflw")
    experiment_plan = subcommands.add_parser(
        "experiment-plan",
        help="Print a dry-run A/B context-probe experiment plan",
    )
    experiment_plan.add_argument("--sprint-id", required=True)
    experiment_plan.add_argument("--repo-path", required=True)
    experiment_plan.add_argument("--packet-path", required=True)
    experiment_plan.add_argument(
        "--evidence-dir",
        help="Override evidence directory; defaults to config evidence dir / sprint id",
    )
    experiment_plan.add_argument(
        "--include",
        dest="include_paths",
        action="append",
        default=[],
        help="Path to include in the context pack; repeatable",
    )
    experiment_plan.add_argument(
        "--ast-grep",
        dest="ast_grep_patterns",
        action="append",
        default=[],
        type=_ast_grep_arg,
        help="Structural probe in name:language:pattern form; repeatable",
    )
    experiment_plan.add_argument(
        "--semgrep-config",
        dest="semgrep_configs",
        action="append",
        default=[],
        help="Semgrep config such as p/python; repeatable",
    )
    digest = subcommands.add_parser(
        "digest",
        help="Read-only operator digest for current state and scout results",
    )
    digest.add_argument("--limit", type=int, default=30)
    digest.add_argument(
        "--include-repo-health",
        action="store_true",
        help="Fetch OpenSSF Scorecard health summaries for configured repos",
    )
    digest.add_argument(
        "--deep-scout",
        action="store_true",
        help="Include comment and existing-PR checks; slower than the default digest",
    )
    digest.add_argument(
        "--include-paid-platforms",
        action="store_true",
        help="Fetch review-only paid platform scout summary",
    )
    digest.add_argument(
        "--include-pr-watch",
        action="store_true",
        help="Include local PR watcher state summary",
    )
    digest.add_argument(
        "--pr-watch-state",
        help="Override PR watcher state path",
    )
    ci_check = subcommands.add_parser("ci-check", help="Classify PR checks")
    ci_check.add_argument("--repo", required=True)
    ci_check.add_argument("--pr", type=int, required=True)
    review_result = subcommands.add_parser(
        "review-result",
        help="Review a worker-result JSON without applying public actions",
    )
    review_result.add_argument("--result-path", required=True)
    apply_result = subcommands.add_parser(
        "apply-result",
        help="Apply the public action proposal from a worker-result JSON",
    )
    apply_result.add_argument("--result-path", required=True)
    subcommands.add_parser("run-once", help="Run one decision loop")
    loop = subcommands.add_parser("loop", help="Run the decision loop forever")
    loop.add_argument("--interval", type=int, default=900)

    args = parser.parse_args()
    config = load_config(args.config, env_path=_existing_path(args.env))
    state_store = StateStore(config.state_path)

    if args.command == "validate":
        print(config.safe_summary())
        return 0
    if args.command == "status":
        print(json.dumps(state_store.load().to_dict(), indent=2, sort_keys=True))
        return 0
    if args.command == "resolve":
        resolved = state_store.resolve_sprint(args.sprint_id, args.status)
        print(json.dumps({"resolved": resolved}, indent=2, sort_keys=True))
        return 0 if resolved else 1
    if args.command == "experiment-plan":
        evidence_dir = (
            Path(args.evidence_dir)
            if args.evidence_dir
            else config.evidence_dir / args.sprint_id
        )
        plan = build_context_probe_experiment(
            sprint_id=args.sprint_id,
            repo_path=Path(args.repo_path),
            packet_path=Path(args.packet_path),
            evidence_dir=evidence_dir,
            include_paths=args.include_paths,
            ast_grep_patterns=args.ast_grep_patterns,
            semgrep_configs=args.semgrep_configs,
        )
        print(json.dumps(plan.to_dict(), indent=2, sort_keys=True))
        return 0
    if args.command == "repo-health":
        report = ScorecardClient().repo_health(args.repo)
        print(json.dumps(report.to_dict(), indent=2, sort_keys=True))
        return 0
    if args.command == "workflow-preflight":
        report = build_workflow_preflight_report(
            config,
            args.repo,
            executable=args.tool,
        )
        print(json.dumps(report.to_dict(), indent=2, sort_keys=True))
        return 0
    if args.command == "target-admission":
        report = build_target_admission_report(
            config,
            args.repo,
            workflow_tool=args.workflow_tool,
        )
        print(json.dumps(report.to_dict(), indent=2, sort_keys=True))
        return 0

    github = GitHubClient(
        secrets=config.secrets,
        timeout_seconds=config.github_timeout_seconds,
    )
    controller = ReputationController(config, github, state_store)
    if args.command == "scan":
        issues = []
        for repo in config.repos:
            if repo.enabled:
                issues.extend(github.list_open_issues(repo.name, limit=args.limit))
        print(
            json.dumps(
                [
                    {
                        "repo": issue.repo,
                        "number": issue.number,
                        "title": issue.title,
                        "url": issue.url,
                        "labels": issue.labels,
                        "assignees": issue.assignees,
                    }
                    for issue in issues
                ],
                indent=2,
                sort_keys=True,
            )
        )
        return 0
    if args.command == "scout":
        report = build_scout_report(
            config,
            github,
            state_store.load(),
            limit=args.limit,
            worker_only=args.worker_only,
        )
        print(json.dumps(report.to_dict(), indent=2, sort_keys=True))
        return 0
    if args.command == "platform-scout":
        report = build_paid_platform_report(
            config,
            github,
            limit=args.limit,
        )
        print(json.dumps(report.to_dict(), indent=2, sort_keys=True))
        return 0
    if args.command == "digest":
        state = state_store.load()
        report = build_scout_report(
            config,
            github,
            state,
            limit=args.limit,
            deep_checks=args.deep_scout,
        )
        repo_health_reports = None
        if args.include_repo_health:
            repo_health_reports = build_repo_health_reports(
                [repo.name for repo in config.repos if repo.enabled]
            )
        paid_platform_summary = None
        if args.include_paid_platforms:
            paid_platform_summary = build_paid_platform_report(
                config,
                github,
                limit=args.limit,
            ).to_digest()
        pr_watch_summary = None
        if args.include_pr_watch:
            pr_watch_path = (
                Path(args.pr_watch_state)
                if args.pr_watch_state
                else config.workspace / config.state_dir.parent / "pr-watch/state.json"
            )
            pr_watch_summary = read_pr_watch_summary(pr_watch_path)
        print(
            json.dumps(
                build_digest(
                    report,
                    state,
                    config,
                    repo_health_reports=repo_health_reports,
                    paid_platform_summary=paid_platform_summary,
                    pr_watch_summary=pr_watch_summary,
                ),
                indent=2,
                sort_keys=True,
            )
        )
        return 0
    if args.command == "ci-check":
        verdict = classify_checks(github.pr_checks(args.repo, args.pr))
        print(json.dumps(verdict.__dict__, indent=2, sort_keys=True))
        return 0
    if args.command == "review-result":
        worker_result = WorkerResult.from_file(Path(args.result_path))
        proposal = worker_result.public_action_proposal
        output = {
            "verdict": worker_result.verdict,
            "summary": worker_result.summary,
            "public_action_review": None,
        }
        if proposal is not None:
            review = review_public_action(
                config,
                proposal,
                ledger_path=config.public_actions_path,
            )
            output["public_action_review"] = review.to_dict()
        print(json.dumps(output, indent=2, sort_keys=True))
        return 0
    if args.command == "apply-result":
        worker_result = WorkerResult.from_file(Path(args.result_path))
        if worker_result.public_action_proposal is None:
            print(json.dumps({"applied": False, "reason": "no proposal"}))
            return 1
        public_actions = controller._review_and_maybe_apply_public_action(
            worker_result.public_action_proposal
        )
        print(json.dumps({"public_actions": public_actions}, indent=2, sort_keys=True))
        return 0 if public_actions and public_actions[0].startswith("performed:") else 1
    if args.command == "run-once":
        result = controller.run_once()
        print(_result_json(result))
        return 0
    if args.command == "loop":
        while True:
            result = controller.run_once()
            print(_result_json(result), flush=True)
            time.sleep(args.interval)
    return 1


def _existing_path(path: str) -> Path | None:
    candidate = Path(path)
    if candidate.exists():
        return candidate
    return None


def _ast_grep_arg(value: str) -> StructuralProbeSpec:
    parts = value.split(":", 2)
    if len(parts) != 3 or not parts[0] or not parts[1] or not parts[2]:
        raise argparse.ArgumentTypeError(
            "--ast-grep must use name:language:pattern form"
        )
    return StructuralProbeSpec(name=parts[0], language=parts[1], pattern=parts[2])


def _result_json(result) -> str:
    return json.dumps(
        {
            "status": result.status,
            "message": result.message,
            "packet_path": str(result.packet_path) if result.packet_path else None,
            "gate_code": result.gate_code,
            "public_actions": result.public_actions or [],
            "diagnostics": result.diagnostics or {},
        },
        indent=2,
        sort_keys=True,
    )


if __name__ == "__main__":
    raise SystemExit(main())
