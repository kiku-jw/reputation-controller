# OSS Reputation Controller: GitHub Tooling Research

Research date: 2026-06-16.

Objective: find GitHub-hosted tools that can strengthen the controller without
turning it into activity theater. The project goal remains proof-or-kill OSS
work: admitted candidate -> local repro/proof -> patch -> verification -> PR or
kill memo.

## Current Controller Gaps

- Context packing is still ad hoc per sprint.
- Runner quality is hard to compare because there is only one main execution
  path.
- Admission could use stronger structural evidence before spending worker
  tokens.
- PR preflight is mostly human/Codex judgment plus repo-native tests.
- Paid/reputation source adapters are still thin beyond the current Opire path.
- The local launchd loop is enough for now; a hosted GitHub App is premature.

## Search Method

- `gh search repos` for issue triage bots, PR review bots, SWE agents, GitHub
  MCP, bounty tooling, and code-search/static-analysis tools.
- `gh repo view` for primary-source snapshots: stars, forks, archive flag,
  license, pushed date, language, and project links.
- Web primary-source checks for current official pages/docs.

The broad "issue triage bot" and "PR review bot" searches mostly returned
zero-star demos. The useful candidates came from mature known categories:
SWE-agent runners, repository context packers, static/structural analysis,
review preflight, GitHub integration frameworks, and paid OSS bounty platforms.

## Shortlist

| Tool | Type | Snapshot signals | Why it fits | Main limits | Verdict |
| --- | --- | ---: | --- | --- | --- |
| [SWE-agent/mini-swe-agent](https://github.com/SWE-agent/mini-swe-agent) | Optional issue runner | 5.2k stars, MIT, active 2026-06 | Small runner for a second opinion on admitted packets; closer to our bounded style than heavy agent stacks. | Should not replace the controller or Codex path; use as probe/verifier first. | Try first |
| [yamadashy/repomix](https://github.com/yamadashy/repomix) | Context packer | 26.3k stars, MIT, active 2026-06 | Creates repeatable AI-friendly repo/context bundles; useful for worker packets and verifier reviews. | Full-repo packing can be wasteful; must use include/exclude filters. | Try first |
| [ast-grep/ast-grep](https://github.com/ast-grep/ast-grep) | Structural search/rewrite | 14.5k stars, MIT, active 2026-06 | Better than raw grep for bug-pattern admission, variant search, and mechanical proof checks. | Needs per-language rule investment; not a finding engine by itself. | Try first |
| [semgrep/semgrep](https://github.com/semgrep/semgrep) | Static analysis | 15.5k stars, LGPL, active 2026-06 | Good targeted rule packs for candidate admission and variant scans across Python/JS/TS/Go/Rust. | Broad scans will create noise; only use scoped rules tied to a concrete bug class. | Try targeted |
| [The-PR-Agent/pr-agent](https://github.com/The-PR-Agent/pr-agent) | AI PR preflight/reviewer | 11.6k stars, Apache-2.0, active 2026-06 | Can become a local pre-PR review stage: summarize diff, risks, tests, docs gaps. | The repo states it is not Qodo's free tier; avoid auto-comments and SaaS lock-in. | Try local/dry-run |
| [reviewdog/reviewdog](https://github.com/reviewdog/reviewdog) | Linter result reporter | 9.4k stars, MIT, active 2026-06 | Strong if we later run our own CI over generated patches and want normalized review output. | Less useful for external repos where we cannot install CI; not a candidate source. | Later |
| [github/github-mcp-server](https://github.com/github/github-mcp-server) | GitHub MCP server | 30.7k stars, MIT, official, active 2026-06 | Direct GitHub access for agents; could simplify some tool plumbing. | Current `gh` CLI is simpler and safer; MCP expands prompt-injection and permission surface. | Avoid for now |
| [probot/probot](https://github.com/probot/probot) | GitHub App framework | 9.6k stars, ISC, active 2026-06 | Right shape if the local controller becomes a hosted GitHub App. | Premature while launchd + `gh` works; adds hosting/webhook/key management. | Later |
| [algora-io/algora](https://github.com/algora-io/algora) and [algora-io/sdk](https://github.com/algora-io/sdk) | Paid OSS source | 1.4k stars on app repo; SDK exists | Adds paid bounty sourcing and contributor/reward metadata. | Need API contract verification and payout/work-claim rules before worker execution. | Add adapter research |
| [Opire/docs](https://github.com/Opire/docs) | Paid OSS source docs | Active docs; API endpoint already known | Existing controller config already has Opire as first paid-platform source. | Public reward API still needs stronger competition/claim-state enrichment. | Strengthen current adapter |

## Rejected Or Deferred

- [OpenHands/OpenHands](https://github.com/OpenHands/OpenHands): very strong
  adoption signal, but too heavy for the current controller. It is a product
  runtime, not a small proof-sprint helper.
- [SWE-agent/SWE-agent](https://github.com/SWE-agent/SWE-agent): strong and
  relevant, but full SWE-agent is heavier than mini-swe-agent for our current
  use. Keep it as a reference architecture.
- [Aider-AI/aider](https://github.com/Aider-AI/aider): excellent interactive
  tool, but it overlaps with Codex rather than strengthening the autonomous
  controller loop.
- [PyGithub/PyGithub](https://github.com/PyGithub/PyGithub) and
  [octokit/graphql.js](https://github.com/octokit/graphql.js): mature API
  clients, but the project intentionally avoids dependencies while `gh` is
  adequate. Revisit only if shelling out becomes brittle.
- [actions/stale](https://github.com/actions/stale),
  [actions/labeler](https://github.com/actions/labeler), and
  [peter-evans/create-pull-request](https://github.com/peter-evans/create-pull-request):
  useful for repos we own, not for an external OSS contribution controller.
- Random "issue triage bot" / "PR review bot" repos from GitHub search:
  mostly zero-star demos. Do not integrate.

## Recommended Implementation Order

1. Add a context-pack step.
   - Use Repomix behind a feature flag.
   - Generate `.controller/evidence/<sprint-id>/context-pack.*`.
   - Start with scoped include lists from the task packet, not full-repo packs.
   - Record file count, byte size, token estimate, and exclusions.

2. Add structural admission probes.
   - Add `ast-grep` first for JS/TS/Python patterns where syntax matters.
   - Add `semgrep` only for scoped rule packs tied to a candidate class.
   - Store results as evidence, not as automatic admission.

3. Add a second-runner experiment.
   - Feed one already-admitted low-risk packet into `mini-swe-agent`.
   - Do not allow it to push, comment, or create PRs.
   - Compare output against current Codex runner on: local repro found, patch
     minimality, test command quality, and kill discipline.

4. Add PR preflight.
   - Try PR-Agent in local/dry-run mode on our own outgoing branch diffs.
   - Only consume its report; do not let it post review comments publicly.
   - Gate on "found real missed issue" before keeping it.

5. Strengthen paid-platform intake.
   - Keep Opire as the first real adapter.
   - Add Algora source research through `algora-io/sdk` and live bounty pages.
   - Normalize both into the same candidate ledger fields: reward, claim
     state, competition, issue age, repo health, local proof command, and kill
     reason.

## Do Not Build Yet

- Hosted GitHub App.
- Full MCP-based GitHub control plane.
- Dashboard.
- Multi-agent queue.
- Auto-PR creation from paid-platform results.

These are downstream of proof yield. The next real improvement is better
evidence per admitted sprint, not more intake.

## Next Experiment

Run a one-sprint A/B test:

- Baseline: current controller packet -> Codex runner -> local verifier.
- Variant: same packet plus Repomix context pack and ast-grep/semgrep probe.

Success condition:

- The variant either kills faster with a better reason or produces a cleaner PR
  packet with less manual context gathering.

Kill condition:

- If the added tools increase setup/context time without improving proof or PR
  quality, remove them.

## Follow-Up GitHub Pass: 2026-06-16 Evening

Purpose: look for additional GitHub-hosted tools and platform sources that can
strengthen the controller after the read-only Opire paid-platform scout landed.
This pass focused on current primary sources and live API probes, not broad
watcher demos.

### Additional Findings

| Tool | Type | Snapshot signals | Why it fits | Main limits | Verdict |
| --- | --- | ---: | --- | --- | --- |
| [ossf/scorecard](https://github.com/ossf/scorecard) | Repo health / security posture API + CLI | 5.5k stars, Apache-2.0, active 2026-06; REST API returned live JSON | Best new pre-admission signal. It can reject or downgrade stale/low-trust repos before worker tokens are spent. Useful checks: `Maintained`, `CI-Tests`, `Code-Review`, `Branch-Protection`, `License`. | Aggregate score is not enough; some checks are security-focused and not directly contribution-yield focused. Use selected checks only. | Try first |
| [bahdotsh/wrkflw](https://github.com/bahdotsh/wrkflw) | Local GitHub Actions validator/runner | 3.2k stars, MIT, active 2026-06 | Better first local-CI probe than full Docker-heavy `act`: validates workflows, supports diff-aware filtering, and can run in emulation/secure-emulation modes. | Does not support service containers; macOS/Windows runner mapping is imperfect. Use for workflow validation and selected jobs, not final CI truth. | Try first |
| [nektos/act](https://github.com/nektos/act) | Local GitHub Actions runner | 70.8k stars, MIT, active 2026-06 | Strong fallback when a repo's CI is hard to reproduce manually and Docker is acceptable. | Heavy, container-specific, often diverges from hosted GitHub runners. Use only after repo-native commands fail to explain CI. | Later |
| [coderamp-labs/gitingest](https://github.com/coderamp-labs/gitingest) | Repo-to-prompt packer | 14.9k stars, MIT, active 2026-06 | Python alternative to Repomix and useful for remote GitHub URL ingestion. Could help read-only scout/verifier context without npm. | Less obviously configurable than Repomix for scoped controller packets. Keep as fallback, not primary. | Runner-up |
| [algora-io/sdk](https://github.com/algora-io/sdk) | Algora bounty SDK | 32 stars, MIT, active enough; README and source show public tRPC endpoint | Gives a real path to an Algora adapter without browser automation: `https://console.algora.io/api/trpc` and `bounty.list.query({ org, limit, status })`. | Org-scoped, not a global feed. Live probe returned empty results for several seeds and even `tscircuit`, while the public page showed open bounties, so route semantics need more proof before adapter work. | Research next |
| [polarsource/polar](https://github.com/polarsource/polar) | Open-source monetization platform | 9.9k stars, Apache-2.0, active 2026-06; official API/SDKs | Useful for monetizing our own public tools later, not for finding paid OSS contribution targets right now. | Not a clear contributor-bounty intake source from GitHub search. Do not mix this into worker intake. | Defer |
| [IssueHunt/readme](https://github.com/IssueHunt/readme) | Issue bounty platform docs | 30 stars, active enough; official readme describes issue-based bounties | Still a possible paid-source surface. | GitHub search did not reveal a clean current public API/source comparable to Opire; likely needs page-level extraction or manual source proof. | Defer |

### Live Checks

- `curl https://api.scorecard.dev/projects/github.com/ossf/scorecard` returned
  `200` with a current Scorecard JSON payload.
- `curl https://api.scorecard.dev/projects/github.com/fossasia/visdom` returned
  `200`; this proves Scorecard can enrich existing configured targets.
- Algora SDK source uses:
  `https://console.algora.io/api/trpc` with `algora.bounty.list.query(...)`.
- Direct public tRPC probes with common org seeds returned empty `items`.
- Public Algora page search showed `tscircuit` open bounties and high claim
  counts, but the SDK/tRPC probe did not return those records. Treat Algora
  adapter as unproven until route/params are reconciled.
- GitHub searches for `github bounty`, `algora bounty`, and AI bounty watchers
  mostly returned 0-4 star demos, crypto escrow experiments, or scraper
  projects. Do not integrate them.

### Revised Recommendation

1. Add a `repo-health` read-only probe using OpenSSF Scorecard REST API.
   - Cache per repo.
   - Do not use aggregate score as a hard gate.
   - Add rejection/downgrade reasons for low `Maintained`, missing license,
     weak `CI-Tests`, and weak `Code-Review`.
   - Store raw selected checks as evidence.

2. Add workflow preflight using `wrkflw validate` first.
   - Start as an optional verifier command after a patch exists.
   - Record workflow validation output in evidence.
   - Only try `wrkflw run` or `act` when repo-native tests do not explain CI.

3. Keep Repomix as primary context packer; keep Gitingest as fallback.
   - Repomix remains better for scoped local packs.
   - Gitingest is interesting when the controller needs quick remote URL
     context or Python-only setup.

4. Research Algora adapter next, but do not implement worker promotion.
   - Add `algora_orgs` seed config only after proving one org returns open
     records through a stable public endpoint.
   - Normalize `reward`, `repo`, `issue`, `title`, `claims`, and source URL.
   - Keep it `review-only`, same as Opire.

5. Do not build from low-star bounty watcher repos.
   - They duplicate our adapter direction, usually rely on scraping, and add no
     trust signal.

### Concrete Next Pack

Smallest useful implementation pack:

- `repo-health --repo owner/name` command.
- `ScorecardClient` using `https://api.scorecard.dev/projects/github.com/{repo}`.
- `RepoHealthReport` with selected checks only.
- Add optional `repo_health` block to `digest`.
- No worker execution changes.
- Tests with fixture JSON and one live smoke command.
