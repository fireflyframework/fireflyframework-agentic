# Spec 4 — Factory Workflows

**Date:** 2026-05-04
**Status:** Draft
**Owner:** Agentic Factory MVP1
**Depends on:** Spec 1 (action runtime), Spec 2 (knowledge base), Spec 3 (specialized agents)
**Required by:** Spec 5 (corpus-search demo runs through these workflows)

---

## Context

The factory's MVP1 control plane is GitHub itself. Each specialized agent (Spec 3) runs as a Docker action; orchestration is six GitHub workflows that chain via `workflow_run`, with artifacts as the medium for typed state between stages and a PR as the final work product. The QA feedback loop is implemented as a workflow that re-dispatches the previous workflow with the prior `QAReport.json` as input — bounded to three iterations.

This spec defines: the workflow file set, their triggers and inputs, the chaining mechanism, the QA loop semantics, concurrency and rate-limit behavior, and the secrets/permissions matrix.

## Non-goals

- Programmatic (non-GitHub) orchestration — MVP2 Spec 6.
- Builder/Deployer agents and their workflows — MVP2 Spec 10.
- Self-hosted runner provisioning. MVP1 uses GitHub-hosted runners. Self-hosted is a deployment-time choice that needs no spec change.
- Cross-repo orchestration (factory drives generation in a *different* target repo). MVP1 generates in the *same* repo where the workflow runs. Cross-repo is a Spec 5 concern (the demo target lives in a separate repo and `factory-run.yml` is invoked there with a copy of the workflows checked in).

## Workflow file set

All under `.github/workflows/`:

| File | Trigger | Output |
|---|---|---|
| `factory-run.yml` | `workflow_dispatch` (input: `intent`) **or** `issues` opened/labeled with `factory:run` | dispatches `factory-define.yml` |
| `factory-define.yml` | `workflow_run` of `factory-run.yml` completed successfully | runs `product_owner` action; uploads `factory-define-<run_id>` artifact |
| `factory-design.yml` | `workflow_run` of `factory-define.yml` | runs `architect`; uploads `factory-design-<run_id>` |
| `factory-generate.yml` | `workflow_run` of `factory-design.yml` **or** repository_dispatch event `factory:retry-generate` (used by the QA loop) | runs `codegen`; opens PR; outputs `pr_number` |
| `factory-qa.yml` | `pull_request` opened/synchronize where label `factory:generated` is present | runs PR's CI, then `qa` action; pass → tag release; fail → repository_dispatch `factory:retry-generate` (or open issue at iteration 3) |
| `factory-knowledge-base-index.yml` | `push` to `knowledge_base/**` on main, **plus** `schedule` (nightly cron) | rebuilds knowledge-base index, uploads as `knowledge-base-index-<sha>` artifact attached to a release tagged `kb-<date>` so downstream actions can fetch it without a workflow run dependency |

## Inputs and chaining

The single source of truth for "what intent are we processing" is the `factory-run.yml` run id. Every downstream workflow receives it as `inputs.run_id` and uses it to scope artifact names (`factory-define-<run_id>`, etc.) and concurrency keys.

`factory-run.yml`:

```yaml
name: factory-run
on:
  workflow_dispatch:
    inputs:
      intent: { description: "Free-text intent", required: true, type: string }
      target_repo: { description: "owner/name of repo to generate into; default = current", required: false, type: string }
  issues:
    types: [opened, labeled]
permissions: { issues: read, actions: write, contents: read }
concurrency:
  group: factory-${{ github.event.issue.number || github.run_id }}
  cancel-in-progress: false
jobs:
  bootstrap:
    if: github.event_name == 'workflow_dispatch' || contains(github.event.issue.labels.*.name, 'factory:run')
    runs-on: ubuntu-latest
    steps:
      - name: persist intent as artifact
        # writes inputs.intent (or issue body) to $RUNNER_TEMP/factory/intent.txt and uploads
      - name: trigger define
        uses: actions/github-script@v7
        # repository_dispatch to factory-define.yml with run_id and intent_artifact_name
```

Each downstream workflow:

1. Downloads the artifacts from prior stages (`actions/download-artifact` filtered by `factory-*-<run_id>`).
2. Downloads the latest `knowledge-base-index-*` release artifact via `gh release download kb-latest`.
3. Runs the agent action (Spec 1 + Spec 3).
4. Uploads the agent's output artifacts.
5. Triggers the next workflow via `repository_dispatch`.

`repository_dispatch` (not `workflow_run`) is preferred for chaining because it accepts typed payloads and avoids the "fan-out by default" semantics of `workflow_run`.

## QA feedback loop

`factory-qa.yml` is the only workflow that closes a loop:

```
on:
  pull_request:
    types: [opened, synchronize]

if: contains(github.event.pull_request.labels.*.name, 'factory:generated')

jobs:
  ci:
    # runs the generated repo's own test workflow via gh workflow run, waits for completion
  qa-agent:
    needs: ci
    # runs the qa action; produces QAReport.json
  decide:
    needs: qa-agent
    steps:
      - if: qa_passed == 'true'
        # tag CalVer (YYYY.MM.PP) on the PR head SHA, comment release notes, end loop
      - if: qa_passed == 'false' && iteration < 3
        # repository_dispatch factory:retry-generate with previous_qa_report artifact ref
      - if: qa_passed == 'false' && iteration == 3
        # open an issue, label factory:needs-human, end loop
```

The `iteration` value is read from a small piece of state stored as a PR label `factory:iteration:<n>` (1, 2, 3). The label is updated on each retry. PR-label state is durable, observable, and avoids needing an external store.

`factory-generate.yml` reacts to `repository_dispatch:factory:retry-generate` by:

1. Loading the `previous_qa_report` artifact.
2. Running `codegen` with `FeedbackContext{iteration, previous_report}`.
3. Force-pushing the new commits to the same branch (so the same PR updates rather than opening a new one). This re-triggers `factory-qa.yml` via the `pull_request: synchronize` event.

Three iterations is the budget. The constant lives in a single workflow input `inputs.max_iterations` (default 3) to ease future tuning.

## Concurrency

Every workflow uses `concurrency: factory-<run_id>` (or `factory-<pr_number>` for `factory-qa.yml`). `cancel-in-progress: false` so a slow build is never killed by a faster one. This guarantees a given intent never has two pipelines racing.

## Secrets and permissions

Repo-level secrets required:
- `ANTHROPIC_API_KEY` (or other provider's; `FACTORY_LLM_PROVIDER` env selects).
- `GITHUB_TOKEN` is auto-provided. Permissions per workflow:
  - `factory-run.yml`: `issues: read, actions: write, contents: read`.
  - `factory-define.yml` / `factory-design.yml`: `contents: read, actions: write`.
  - `factory-generate.yml`: `contents: write, pull-requests: write, actions: write`.
  - `factory-qa.yml`: `contents: write` (for tag), `pull-requests: write`, `issues: write` (for the iteration-3 escalation), `actions: read`.
  - `factory-knowledge-base-index.yml`: `contents: write` (release artifact upload).

OIDC is not used in MVP1; it becomes relevant when the deployer agent lands in MVP2 Spec 10 and needs cloud credentials.

## Rate-limit and cost considerations

- Anthropic API rate limits: a single full intent uses 4 LLM-bound stages × ~1 call/stage × Reflexion (~3 calls in codegen, ~2 in qa) = ~10 LLM requests, well under any per-minute limit for a single intent. Two concurrent intents are safe; ten are not. The `concurrency` block prevents per-intent races but does not throttle across intents — `factory-run.yml` rejects new dispatches with a comment when more than 5 factory runs are active org-wide. The check is a simple `gh api` call counting in-progress runs whose name starts with `factory-`.
- GitHub Actions concurrent-job limits: GitHub-hosted runners cap at 20 concurrent jobs on free plans, 60+ on team. Keep parallel jobs minimal: each workflow has at most 2 jobs (CI + agent for QA; bootstrap + dispatch for run).
- Artifact retention: GitHub default 90 days. Sufficient for MVP1.

## Observability surfaces

- `$GITHUB_STEP_SUMMARY` of each agent step: a markdown table with cost, tokens, model used, retrieved skills, time elapsed.
- `factory-qa.yml`'s decide job posts a single PR comment per iteration with the QAReport summary.
- The release notes generated on green QA include the link to all four agent runs.
- All trace IDs are written to `$GITHUB_OUTPUT` so an external collector (when added in MVP2) can correlate runs.

## Verification

- A `workflow_dispatch` of `factory-run.yml` with intent `"Generate a hello-world REST endpoint"` against a fixture target repo lands a green PR within 30 minutes and tags `2026.05.0`. (Demo content for this is Spec 5.)
- A perturbation test: hand-edit one passing test in the generated repo to fail; force-push to the PR. `factory-qa.yml` triggers, iteration label flips to 2, `factory-generate.yml` re-runs, force-pushes a fix, qa passes, release tag appears.
- A budget-exhaustion test: hand-edit a test that codegen cannot fix (e.g. asserts an external service is reachable); after iteration 3 an issue with label `factory:needs-human` is opened and the loop stops.
- `act -W .github/workflows/factory-qa.yml` runs locally with stubbed agent outputs.

## Open questions

- Should `factory-generate.yml` open a new PR per intent, or update an existing one when re-running? Spec proposes one PR per intent, force-updated on retries — simplifies the iteration label and keeps history linear. Confirm during implementation.
- The cross-org concurrency cap (`> 5 active factory runs`) is hand-rolled. If the factory becomes popular this is a footgun; revisit when we hit it.
- Tag format `YYYY.MM.PP`: `PP` is the patch counter within a month. Need a tiny script to compute it from `git tag --list "YYYY.MM.*"`. Spec 5 covers this in its tooling section.
