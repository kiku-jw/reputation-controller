# OSS Reputation Controller

Dry-run-first controller for proof-first OSS contribution loops.

The controller is not a PR spammer. It enforces WIP locks, creates bounded task
packets, watches GitHub Actions, and keeps public actions disabled until the
config explicitly allows them.

## Current v0

- Local Python CLI using only stdlib plus the external `gh` CLI.
- Default `dry_run=true`.
- One active sprint at a time.
- Repo allowlist from `config/controller.example.json`.
- Token-safe `.env.example`.
- Safety gates for public comments, PR creation, force-push, WIP limits, and
  forbidden title terms such as `codex`.
- Bounded GitHub CLI calls so a single slow `gh` lookup cannot hang the loop
  indefinitely.
- GitHub issue scan and PR check classification.
- Read-only multi-repo scout with admission/rejection reasons.
- Read-only paid-platform scout for review-only bounty candidates.
- Read-only repo health probe through OpenSSF Scorecard.
- Optional review-only workflow preflight through `wrkflw validate` when
  installed.
- Read-only target admission probe for deciding whether a scout-only repo is
  ready for worker execution.
- Operator digest for current state, policy, candidates, rejection counts, and
  optional repo health, paid-platform, and PR-watch visibility.
- Optional worker execution for bounded `codex exec` packets.
- Public action review with a JSONL ledger under `.controller/public-actions.jsonl`.

## Setup

```bash
cd reputation-controller
cp .env.example .env
```

Fill `.env` locally. Do not paste tokens into chat.

For an OpenAI-compatible model endpoint:

```bash
LLM_API_KEY=...
LLM_BASE_URL=https://api.openai.com/v1
LLM_MODEL=...
```

For GitHub, prefer a GitHub App installation token. A fine-grained PAT is okay
for v0 if it is limited to selected repos and has an expiry.

## Commands

```bash
python3 -m reputation_controller --config config/controller.example.json validate
python3 -m reputation_controller --config config/controller.example.json status
python3 -m reputation_controller --config config/controller.example.json scan --limit 20
python3 -m reputation_controller --config config/controller.example.json scout --limit 20
python3 -m reputation_controller --config config/controller.example.json scout --worker-only --limit 20
python3 -m reputation_controller --config config/controller.example.json platform-scout --limit 20
python3 -m reputation_controller --config config/controller.example.json repo-health --repo fossasia/visdom
python3 -m reputation_controller --config config/controller.example.json workflow-preflight --repo fossasia/visdom
python3 -m reputation_controller --config config/controller.example.json target-admission --repo fossasia/eventyay
python3 -m reputation_controller --config config/controller.example.json digest --limit 20
python3 -m reputation_controller --config config/controller.example.json digest --limit 20 --include-repo-health
python3 -m reputation_controller --config config/controller.example.json digest --limit 20 --include-paid-platforms --include-pr-watch
python3 -m reputation_controller --config config/controller.example.json experiment-plan --sprint-id fossasia-visdom-1431 --repo-path ../visdom --packet-path ../.controller/tasks/fossasia-visdom-1431.md --include py --include test --ast-grep 'broad-except:python:except Exception:' --semgrep-config p/python
python3 -m reputation_controller --config config/controller.example.json run-once
python3 -m reputation_controller --config config/controller.example.json resolve --sprint-id fossasia-visdom-1431 --status needs-human
python3 -m reputation_controller --config config/controller.example.json ci-check --repo fossasia/visdom --pr 1456
python3 -m reputation_controller --config config/controller.example.json review-result --result-path .controller/evidence/<sprint-id>/worker-result.json
python3 -m reputation_controller --config config/controller.example.json apply-result --result-path .controller/evidence/<sprint-id>/worker-result.json
python3 -m reputation_controller --config config/controller.example.json loop --interval 900
```

Use `PYTHONPATH=src` unless the package is installed editable.

## Repo Target Modes

Each repo has two switches:

- `enabled=true`: include the repo in read-only `scan`, `scout`, and `digest`.
- `worker_enabled=true`: allow `run-once` to create a task packet and eventually
  run a worker for that repo.
- `proof_commands=[...]`: repo-level proof command templates used by
  `target-admission` and task packets as reviewable readiness evidence. They
  are not executed by `target-admission`.

Scout-only repos should use `enabled=true` and `worker_enabled=false` until a
local checkout, repo instructions, branch policy, and proof commands are ready.
This lets the controller widen intake without widening public or token-spending
execution.

Current default target shape:

- `fossasia/visdom`: scout + worker.
- `Giskard-AI/giskard-oss`: scout + worker, currently restricted by
  `worker_issue_allow=[2511]`; current live scout rejects it because PR `#2512`
  is already open.
- `NVIDIAGameWorks/kaolin`, `NVIDIAGameWorks/dxvk-remix`,
  `NVIDIAGameWorks/rtx-remix`,
  `fossasia/eventyay`, `fossasia/pslab-app`, `fossasia/badgemagic-app`,
  `fossasia/voxbento`: scout-only.

## Recurring Loop

Local foreground loop:

```bash
scripts/run-controller-loop.sh
```

Use your operating system scheduler of choice if you want recurring runs. Keep
machine-specific scheduler files, logs, and credentials outside this repository.

## Paid Platform Scout

`platform-scout` is review-only. It never writes controller state, creates task
packets, runs workers, posts comments, or opens PRs. Current config uses Opire's
public rewards endpoint as the first paid-platform source and applies the same
proof-or-kill shape before a human spends attention:

- reward must clear the configured minimum,
- URL must be a GitHub issue,
- live GitHub issue must still be open and unassigned,
- denied labels are rejected,
- crowded solver/claim lanes are rejected,
- existing open PRs are rejected,
- broad/non-proof titles are rejected.

Promotion from paid-platform scout to worker execution is intentionally a
separate future change after the platform and one concrete candidate are
manually verified.

## Repo Health And Workflow Preflight

`repo-health` is advisory. It queries OpenSSF Scorecard for selected checks such
as `Maintained`, `CI-Tests`, `Code-Review`, `License`, and
`Branch-Protection`, then reports `pass`, `downgrade`, or `error`.

`workflow-preflight` is also advisory. It checks the configured local checkout
and, when `wrkflw` is installed, runs:

```bash
wrkflw validate .github/workflows
```

If `wrkflw` is missing, the checkout is missing, or no workflows exist, the
command returns an explicit review status instead of guessing success.

Neither command writes controller state, creates task packets, runs workers,
posts comments, or opens PRs.

## Target Admission

`target-admission` is the promotion check before turning a scout-only repo into
worker execution:

```bash
python3 -m reputation_controller --config config/controller.example.json target-admission --repo fossasia/eventyay
```

It reports configured status, local checkout presence, current branch, repo
instruction files, proof commands, workflow preflight, and repo health. It does
not write state, run proof commands, run workers, post comments, or open PRs.

Expected blocker examples:

- `worker_disabled`: the repo is intentionally scout-only.
- `repo_checkout_missing`: no local checkout under the configured workspace.
- `proof_commands_missing`: no explicit proof command template is configured.

Review notes such as `checkout_not_on_default_branch`, `workflow_preflight_tool_missing`,
or `repo_health_weak_branch_protection` are advisory and should be resolved or
accepted before enabling workers.

## Public Action Policy

The controller never posts comments, creates PRs, force-pushes, merges, or
comments on reviews unless the corresponding config/env flag is enabled.

Guarded public mode starts with issue comments only:

```text
CONTROLLER_DRY_RUN=false
CONTROLLER_ALLOW_WORKER_EXECUTION=true
CONTROLLER_ALLOW_PUBLIC_COMMENTS=true
CONTROLLER_PUBLIC_ACTION_MODE=issue-comment
CONTROLLER_ALLOW_PR_CREATE=false
CONTROLLER_ALLOW_FORCE_PUSH=false
```

Draft PR creation requires a separate explicit override, a pushed branch, and
an evidence-backed `worker-result.json`.

## Runtime Artifacts

Default workspace root from `config/controller.example.json`:

```text
..
```

Generated artifacts:

```text
.controller/state/state.json
.controller/tasks/<sprint-id>.md
.controller/evidence/<sprint-id>/
.controller/public-actions.jsonl
```

Resolve an active sprint after the worker or human verdict:

```bash
PYTHONPATH=src python3 -m reputation_controller --config config/controller.example.json resolve --sprint-id <sprint-id> --status kill
```

## License

MIT.
