# Reputation Controller v0 Design

## Goal

Build a local 24/7-capable OSS reputation controller that moves from repo
allowlist to bounded proof sprint without creating public noise.

## Non-Goals

- No auto-merge.
- No automatic public comments.
- No automatic PR creation in default config.
- No broad vulnerability scanning.
- No generic issue farming.
- No worker execution from paid-platform scout output until a specific platform
  and candidate have been manually verified and promoted.
- No worker execution from repo-health or workflow-preflight output; these are
  advisory evidence probes only.
- No worker execution from target-admission output; it is a promotion review
  surface, not an automatic promotion mechanism.

## Control Loop

1. Load config and dotenv secrets.
2. Load persistent state.
3. Enforce WIP gates.
4. Scan enabled allowlist repos through `gh`.
5. Admit one unassigned, non-dependency candidate.
6. Create a task packet with required proof, forbidden actions, and stop rules.
7. Persist the sprint in state.
8. Let a human or later worker runner execute the packet.
9. Watch PR CI through `ci-check` once a PR exists.

## Paid Platform Scout

Paid-platform scouting is a separate read-only loop. It normalizes rewards into
GitHub issue candidates, enriches them through live GitHub checks, and applies
proof-or-kill rejection reasons. It deliberately stops at review output rather
than creating `.controller/tasks/*` packets.

## Advisory Probes

Repo health and workflow preflight are read-only advisory probes. Repo health
uses selected OpenSSF Scorecard checks to highlight maintenance, CI, review, and
license risk. Workflow preflight validates local GitHub Actions configuration
through `wrkflw` when installed. Both enrich human/controller review but do not
select candidates, create packets, run workers, or perform public actions.

Target admission is the review boundary for scout-only repos. It collects local
checkout state, branch state, repo instructions, proof command templates,
workflow preflight, and repo health into one JSON report. Promotion to
`worker_enabled=true` remains a separate config change.

Digest visibility can include paid-platform and PR-watch summaries on request.
Those blocks explain current opportunity and review state but are not consumed
by `run-once`.

## Safety Invariants

- Secrets are never stored in state or packet files.
- `dry_run=true` by default.
- One active sprint at a time.
- GitHub CLI calls are time-bounded.
- Public actions need explicit config flags.
- PR titles containing forbidden terms such as `codex` are blocked.
- Sourcery quota skips are external skips, not code failures.

## Extension Path

v1 can add an explicit worker executor that runs the prepared `codex exec`
command and stores logs under `.controller/evidence/<sprint-id>/`. The executor
should stay behind a separate allow flag so packet creation and public actions
remain independently gated.
