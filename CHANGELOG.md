# Changelog

All notable changes to this action are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and versions follow
[semantic versioning](https://semver.org).

## [Unreleased]

## [1.0.0] - 2026-10-21

First public release.

### Added

- Runs a `traccia eval` or `traccia-ts eval` command and exits with its exit code.
- Refuses a missing, unreadable, or inconsistent `summary.json` with exit 5, and deletes any old summary before the run.
- Records the commit, head commit, branch, base branch, pull request, repository, and actor on the experiment through `TRACCIA_GIT_*` variables. Values the job already set take precedence.
- Creates one pull request comment per `comment_key` and updates it on later pushes. The comment has a scorer table with baseline and change, failures, gates, and links to the experiment and the run. The eval command cannot read `github_token`. A custom GitHub App token posts a new comment on each run, because it cannot be recognised as the previous author. The default token updates the existing comment.
- Writes a job summary that includes the full `summary.json`.
- Inputs: `command`, `summary`, `working_directory`, `comment`, `comment_key`, `github_token`.
- Outputs: `exit_code`, `code`, `label`, `quality_gate`, `experiment_id`, `experiment_url`, `summary_path`, `comment_posted`.
- Support for GitHub Enterprise Server through `GITHUB_API_URL`.
