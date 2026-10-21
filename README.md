# Traccia Eval Action

[![Test](https://github.com/traccia-ai/traccia-eval-action/actions/workflows/test.yml/badge.svg)](https://github.com/traccia-ai/traccia-eval-action/actions/workflows/test.yml)
[![License](https://img.shields.io/badge/license-Apache%202.0-blue.svg)](LICENSE)

Gate pull requests on a [Traccia](https://traccia.ai) eval and post the result as a pull request comment.

The action runs your `traccia eval` (Python) or `traccia-ts eval` (TypeScript) command, checks that the result file is fresh and consistent, comments the scores on the pull request, and exits with the eval's exit code. A regression fails the check the same way a failing unit test does.

```yaml
- uses: traccia-ai/traccia-eval-action@v1
  with:
    command: traccia eval evals/agent.py --dataset golden --scorer exact_match --min-pass-rate 0.9 --output summary.json
  env:
    TRACCIA_API_KEY: ${{ secrets.TRACCIA_API_KEY }}
```

## Contents

- [Do you need this action?](#do-you-need-this-action)
- [Quickstart](#quickstart)
- [What the comment looks like](#what-the-comment-looks-like)
- [Inputs](#inputs)
- [Outputs](#outputs)
- [Exit codes](#exit-codes)
- [Recipes](#recipes)
- [How it works](#how-it-works)
- [Security](#security)
- [Versioning](#versioning)
- [Development](#development)

## Do you need this action?

No. The pass/fail decision is made by the Traccia CLI, not by this action. Running the CLI directly in a `run:` step gates merges the same way. The action adds the parts that are tedious to write yourself:

| | CLI in a `run:` step | This action |
|---|:---:|:---:|
| Fails the check on a regression | ✅ | ✅ |
| Saves the run as an experiment in Traccia | ✅ | ✅ |
| Records the commit, branch, and pull request on the experiment | set 8 env vars yourself | ✅ |
| Pull request comment, updated on every push | | ✅ |
| Job summary with the full result | | ✅ |
| Refuses a stale or inconsistent result file | | ✅ |
| Step outputs (`exit_code`, `experiment_url`, ...) | | ✅ |

To go without the action, copy [`examples/without-action.yml`](examples/without-action.yml).

## Quickstart

**Before you start**

1. Save a dataset and at least one scorer in the Traccia app. A builtin such as `exact_match` is enough.
2. Create a workspace API key under **Settings → API Keys**, and add it to your repository as the secret `TRACCIA_API_KEY`.
3. Add the SDK to your project's dependencies: `traccia` for Python or `@traccia/sdk` for TypeScript. The action uses the version your lockfile installs. It never installs the SDK itself.
4. Write a task: a function that takes a dataset row's input and returns your app's output. See [Run Evals In CI](https://traccia.ai/docs/guides/ci-evals/).

**Add the workflow.** Save this as `.github/workflows/evals.yml`:

```yaml
name: Evals

on:
  pull_request:

permissions:
  contents: read
  pull-requests: write # lets the action post the result comment

jobs:
  eval:
    runs-on: ubuntu-latest
    timeout-minutes: 30
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.12"
      - run: pip install -r requirements.txt # must include traccia

      - uses: traccia-ai/traccia-eval-action@v1
        with:
          command: >-
            traccia eval evals/support_agent.py
            --dataset support-golden
            --scorer exact_match
            --min-pass-rate 0.9
            --output summary.json
        env:
          TRACCIA_API_KEY: ${{ secrets.TRACCIA_API_KEY }}
```

**Block merges on it.** In the repository settings, add the `eval` job as a required status check in your branch protection rule or ruleset.

More complete workflows are in [`examples/`](examples):

| File | Shows |
|---|---|
| [`python.yml`](examples/python.yml) | The quickstart above |
| [`typescript.yml`](examples/typescript.yml) | Node with `npm ci` and `npx --no-install traccia-ts` |
| [`baseline.yml`](examples/baseline.yml) | Fail on a drop against the production prompt, plus a cost cap |
| [`matrix.yml`](examples/matrix.yml) | One eval per model, one comment per model, summaries as artifacts |
| [`without-action.yml`](examples/without-action.yml) | The same gate with only the CLI |

## What the comment looks like

One comment per job is created on the first run and edited on every later push.

> ❌ **Traccia Eval failed** · `regression` (exit 1)
>
> | Scorer | Pass rate | Baseline | Change | Graded |
> |---|---|---|---|---|
> | `exact_match` | 84.0% | 90.0% | −6.0 pts | 50/50 |
>
> **Failures**
> - `regression` exact_match dropped more than allowed
>
> **Gates:** Max drop 5 pts · Baseline `8c1d77e2-5b0`
>
> [Open experiment](#) · [View run](#) · commit `4b7e19c`

A passing run reads **✅ Traccia Eval passed · Quality Gate**. A run with no pass-rate gate reads **Execution Only**. Cost and latency gates can still apply. Informational scorers are listed and marked, and a scorer with missing or errored rows shows `incomplete` instead of a misleading rate.

## Inputs

| Input | Default | Description |
|---|---|---|
| `command` | **required** | The eval command. It must write a summary with `--output`. For TypeScript use `npx --no-install traccia-ts eval ...`. |
| `summary` | `summary.json` | Path of the summary file. Must match the command's `--output`. |
| `working_directory` | workspace root | Directory to run the command in. `summary` is relative to it. |
| `comment` | `true` | Set to `false` to skip the pull request comment. The job summary is still written. |
| `comment_key` | workflow, job, and ref | Identifies this job's comment. In a matrix, include the matrix value, for example `support-${{ matrix.model }}`. |
| `github_token` | `${{ github.token }}` | Token used to post the comment. Needs `pull-requests: write`. The eval command cannot read it. |

Secrets the eval needs, such as `TRACCIA_API_KEY` or a model provider key, go in the step's `env:`. The command can read any environment variable, for example `--dataset "$DATASET"`.

The default token and a personal access token update the same comment on later pushes. A custom GitHub App token cannot call `GET /user`, so the action treats the poster as `github-actions[bot]`. It will not recognise a comment that app already posted as `myapp[bot]`, and each run adds a new comment. Use the default token when the comment should be updated in place.

## Outputs

| Output | Example | Description |
|---|---|---|
| `exit_code` | `1` | The eval exit code. See [Exit codes](#exit-codes). |
| `code` | `regression` | The first failure code. Empty on a pass. |
| `label` | `Failed` | `Quality Gate`, `Execution Only`, or `Failed`. |
| `quality_gate` | `false` | `true` only when a pass-rate bar was set and passed. |
| `experiment_id` | `0f6e2a54-…` | Id of the saved experiment. |
| `experiment_url` | `https://app.traccia.ai/…` | Link to the experiment. |
| `summary_path` | `/home/runner/work/…/summary.json` | Absolute path of the summary, for `actions/upload-artifact`. |
| `comment_posted` | `true` | Whether the pull request comment was created or updated. |

Outputs are set even when the step fails, so a later step with `if: always()` can read them:

```yaml
- id: eval
  uses: traccia-ai/traccia-eval-action@v1
  with:
    command: traccia eval evals/agent.py --dataset golden --scorer exact_match --min-pass-rate 0.9 --output summary.json
  env:
    TRACCIA_API_KEY: ${{ secrets.TRACCIA_API_KEY }}

- name: Notify on regression
  if: always() && steps.eval.outputs.code == 'regression'
  run: echo "Regression, see ${{ steps.eval.outputs.experiment_url }}"
```

## Exit codes

The step exits with the CLI's code. Problems with the evidence are reported before quality, so a crash is never mistaken for a low score.

| Exit | Meaning | Typical codes |
|---|---|---|
| `0` | Passed | |
| `1` | Below the bar | `threshold_missed`, `regression`, `cost_increase`, `latency_increase`, `dataset_changed` |
| `2` | The command or baseline can't be used; nothing ran | `bad_flags`, `unknown_scorer`, `baseline_missing` |
| `3` | The run happened but its results can't be trusted | `task_error`, `scorer_error`, `scorer_coverage`, `dataset_drift` |
| `4` | The run finished but could not be saved | `persist_failed` |
| `5` | No trustworthy summary | `summary_failed` |

The action returns `5` on its own when the summary file is missing, is not valid JSON, or records a different exit code from the one the process returned. The full list of codes is in the [CLI reference](https://traccia.ai/docs/reference/cli/).

## Recipes

**TypeScript.** Install with `npm ci`, then call the CLI through `npx --no-install` so the lockfile version is used. The action's shell does not put `node_modules/.bin` on `PATH`. See [`examples/typescript.yml`](examples/typescript.yml).

**Compare against production.** Add `--baseline-prompt <name> --max-drop 0.05` to fail when any scorer drops more than 5 points below the experiment attached to the production prompt. Setup is in [Compare Against A Baseline](https://traccia.ai/docs/guides/ci-evals/#baseline).

**Matrix.** Give each leg its own `comment_key`, otherwise the legs overwrite one comment. See [`examples/matrix.yml`](examples/matrix.yml).

**Monorepo.** Set `working_directory: services/support` to run the command there. `summary` is resolved from that directory.

**Keep the summary.** Upload `steps.<id>.outputs.summary_path` with `actions/upload-artifact` and `if: always()`.

**Record the branch tip instead of the merge commit.** On `pull_request`, `actions/checkout` checks out GitHub's merge commit by default. To test the branch tip, check out with `ref: ${{ github.event.pull_request.head.sha }}`. The experiment records both the commit that ran and the head commit.

**Fork pull requests.** GitHub does not give secrets to workflows from forks, so the eval cannot authenticate. Skip those runs:

```yaml
jobs:
  eval:
    if: github.event.pull_request.head.repo.full_name == github.repository
```

Do not switch to `pull_request_target` to get secrets. It would run the fork's code with your API key.

## How it works

1. Exports the git metadata the CLI records on the experiment (`TRACCIA_GIT_CHECKOUT_SHA`, `TRACCIA_GIT_HEAD_SHA`, `TRACCIA_GIT_HEAD_REF`, `TRACCIA_PR_NUMBER`, and others). A value your job already set takes precedence.
2. Deletes any existing summary file, so a result from an earlier run can never be published as this run's.
3. Runs `command` with `bash -c` in `working_directory`, inside a collapsible log group. The comment token is removed from that command's environment.
4. Reads the summary. If it is missing, unreadable, or its `exit_code` differs from the process exit code, the result becomes exit `5`.
5. Writes the job summary and the step outputs.
6. Creates or updates the pull request comment. The comment is found by a hidden marker, `<!-- traccia-eval:<comment_key> -->`. If posting fails, the job summary says why and the check result does not change.
7. Exits with the eval's exit code.

The action is a composite action: bash plus standard-library Python 3. It runs on Linux and macOS runners, GitHub-hosted or self-hosted. It works with GitHub Enterprise Server through `GITHUB_API_URL`.

## Security

- **No script injection.** Inputs and event fields reach the script as environment variables. They are never interpolated into shell code by the action.
- **Least privilege.** The action needs `contents: read`, plus `pull-requests: write` for the comment. Nothing else. The comment token is not in the eval command's environment.
- **Untrusted text is escaped.** Failure messages and scorer names are escaped before they go into the comment, and only `http(s)` experiment links are rendered.
- **Pin by SHA for supply-chain safety.** `@v1` follows the latest 1.x release. To lock an exact version, pin the full commit SHA of a release, for example `traccia-ai/traccia-eval-action@<sha> # v1.0.0`.

To report a vulnerability, use [private vulnerability reporting](https://github.com/traccia-ai/traccia-eval-action/security/advisories/new). Do not open a public issue.

## Versioning

Releases follow [semantic versioning](https://semver.org) and are listed in [CHANGELOG.md](CHANGELOG.md).

- `v1.2.3` is an immutable release tag.
- `v1` is a moving tag that points to the latest `1.x.y`. A breaking change ships as `v2`.

The action reads `summary.json` schema version `1`, written by `traccia` and `@traccia/sdk`. A newer schema is still processed, and the comment says to upgrade the action.

## Development

The tests need only Python 3.10 or later. There are no dependencies to install.

```bash
python3 -m unittest discover -s tests -v
```

| Path | What it is |
|---|---|
| `action.yml` | Inputs, outputs, and the single composite step |
| `run.sh` | Orchestration: git metadata, run the command, call the two scripts below |
| `src/summary.py` | Checks the summary and renders the comment, job summary, and outputs |
| `src/comment.py` | Creates or updates the pull request comment |
| `tests/` | Unit tests, end-to-end tests of `run.sh`, and a fake GitHub API |
| `.github/workflows/test.yml` | Offline tests, shellcheck, actionlint, and a self-test of the action |

See [CONTRIBUTING.md](CONTRIBUTING.md).

## License

[Apache License 2.0](LICENSE)
