#!/usr/bin/env bash
# Traccia Eval action entry point.
#
# Runs the user's eval command, refuses a stale or inconsistent summary, posts
# the result, and exits with the eval's own exit code. The step result is the
# check result; posting the comment can fail without changing it.
set -u

action_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
EXIT_SUMMARY=5

py="$(command -v python3 || command -v python || true)"
if [[ -z "$py" ]]; then
  echo "::error title=Traccia Eval::Python 3 is required on the runner."
  exit "$EXIT_SUMMARY"
fi

if [[ -n "${TRACCIA_EVAL_WORKING_DIRECTORY:-}" ]]; then
  cd "$TRACCIA_EVAL_WORKING_DIRECTORY" || {
    echo "::error title=Traccia Eval::working_directory '$TRACCIA_EVAL_WORKING_DIRECTORY' does not exist."
    exit "$EXIT_SUMMARY"
  }
fi

# Git metadata the CLI stores on the experiment. Values the job already set win.
checkout_sha="$(git rev-parse HEAD 2>/dev/null || true)"
export TRACCIA_GIT_CHECKOUT_SHA="${TRACCIA_GIT_CHECKOUT_SHA:-$checkout_sha}"
export TRACCIA_GIT_GITHUB_SHA="${TRACCIA_GIT_GITHUB_SHA:-${GITHUB_SHA:-}}"
export TRACCIA_GIT_HEAD_SHA="${TRACCIA_GIT_HEAD_SHA:-${GITHUB_HEAD_SHA:-$checkout_sha}}"
export TRACCIA_GIT_HEAD_REF="${TRACCIA_GIT_HEAD_REF:-${GITHUB_HEAD_REF:-}}"
export TRACCIA_GIT_BASE_REF="${TRACCIA_GIT_BASE_REF:-${GITHUB_BASE_REF:-}}"
export TRACCIA_PR_NUMBER="${TRACCIA_PR_NUMBER:-${PR_NUMBER:-}}"
export TRACCIA_GIT_REPOSITORY="${TRACCIA_GIT_REPOSITORY:-${GITHUB_REPOSITORY:-}}"
export TRACCIA_GIT_ACTOR="${TRACCIA_GIT_ACTOR:-${GITHUB_ACTOR:-}}"

summary_path="${TRACCIA_EVAL_SUMMARY:-summary.json}"
# A summary left over from an earlier run must never be published as this run's result.
if ! rm -f -- "$summary_path"; then
  echo "::error title=Traccia Eval::Could not remove the previous summary at ${summary_path}."
  exit "$EXIT_SUMMARY"
fi

echo "::group::traccia eval"
status=0
# The comment token stays in this shell for comment.py. The eval must not see it.
env -u TRACCIA_EVAL_GITHUB_TOKEN bash -c "$TRACCIA_EVAL_COMMAND" || status=$?
echo "::endgroup::"

work="$(mktemp -d)"
trap 'rm -rf "$work"' EXIT

comment_key="${TRACCIA_EVAL_COMMENT_KEY:-}"
if [[ -z "$comment_key" ]]; then
  comment_key="${GITHUB_WORKFLOW:-eval}-${GITHUB_JOB:-job}-${GITHUB_REF_NAME:-run}"
fi

run_url=""
if [[ -n "${GITHUB_REPOSITORY:-}" && -n "${GITHUB_RUN_ID:-}" ]]; then
  run_url="${GITHUB_SERVER_URL:-https://github.com}/${GITHUB_REPOSITORY}/actions/runs/${GITHUB_RUN_ID}"
fi

"$py" "$action_dir/src/summary.py" \
  --summary "$summary_path" \
  --status "$status" \
  --checkout-sha "$checkout_sha" \
  --comment-key "$comment_key" \
  --run-url "$run_url" \
  --comment-out "$work/comment.md" \
  --status-out "$work/status"

final="$(cat "$work/status" 2>/dev/null || true)"
if [[ ! "$final" =~ ^[0-9]+$ ]]; then
  echo "::error title=Traccia Eval::Could not read the eval summary."
  final="$EXIT_SUMMARY"
fi

note=""
posted="false"
if [[ "${TRACCIA_EVAL_COMMENT:-true}" != "true" ]]; then
  :
elif [[ -z "${PR_NUMBER:-}" ]]; then
  :
elif [[ -z "${TRACCIA_EVAL_GITHUB_TOKEN:-}" ]]; then
  note="The pull request comment was not posted because no token was available."
elif [[ -f "$work/comment.md" ]] && "$py" "$action_dir/src/comment.py" "$work/comment.md"; then
  posted="true"
else
  note="The pull request comment was not posted. Grant \`pull-requests: write\`; fork pull requests cannot be commented on."
fi

if [[ -n "$note" ]]; then
  echo "::warning title=Traccia Eval::$note The check result is still the eval exit code."
  [[ -n "${GITHUB_STEP_SUMMARY:-}" ]] && echo "> $note The check result is still the eval exit code." >> "$GITHUB_STEP_SUMMARY"
fi
[[ -n "${GITHUB_OUTPUT:-}" ]] && echo "comment_posted=$posted" >> "$GITHUB_OUTPUT"

exit "$final"
