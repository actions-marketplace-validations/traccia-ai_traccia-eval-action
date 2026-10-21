"""Create or update this job's pull request comment.

The first line of the comment is an HTML marker. A later update edits the comment
only when that line is exactly the marker and the comment belongs to the
authenticated user or their GitHub App. A contributor quoting the marker is left
alone. A failure here never changes the eval result; the caller only records a note.
Standard library only, Python 3.8+.
"""

from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.request
from typing import Any, Dict, List, Optional

PAGE_SIZE = 100
TIMEOUT_SEC = 20


def _request(method: str, url: str, token: str, payload: Optional[Dict[str, Any]] = None) -> Any:
    data = json.dumps(payload).encode("utf-8") if payload is not None else None
    request = urllib.request.Request(
        url,
        data=data,
        method=method,
        headers={
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "traccia-eval-action",
            **({"Content-Type": "application/json"} if data is not None else {}),
        },
    )
    with urllib.request.urlopen(request, timeout=TIMEOUT_SEC) as response:
        raw = response.read()
    return json.loads(raw) if raw else None


def _first_line(body: str) -> str:
    text = body or ""
    return text.splitlines()[0].strip() if text else ""


# The workflow's GITHUB_TOKEN posts as this bot and cannot call GET /user.
ACTIONS_BOT = "github-actions[bot]"


def _identity(api: str, token: str) -> Dict[str, str]:
    try:
        user = _request("GET", f"{api}/user", token)
    except urllib.error.HTTPError as exc:
        if exc.code == 403:
            try:
                exc.read()
            finally:
                exc.close()
            return {"login": ACTIONS_BOT}
        raise
    if not isinstance(user, dict) or not str(user.get("login") or "").strip():
        raise ValueError("Could not identify the authenticated GitHub user")
    return {"login": str(user["login"]).strip()}


def _owns(item: Dict[str, Any], identity: Dict[str, str]) -> bool:
    user = item.get("user") if isinstance(item.get("user"), dict) else {}
    login = str(user.get("login") or "")
    if login and login == identity["login"]:
        return True
    app = item.get("performed_via_github_app") if isinstance(item.get("performed_via_github_app"), dict) else {}
    slug = str(app.get("slug") or "")
    return bool(slug and identity["login"] == f"{slug}[bot]")


def find_comment(api: str, repo: str, pr: str, token: str, marker: str) -> Optional[Dict[str, Any]]:
    identity = _identity(api, token)
    page = 1
    while True:
        batch = _request("GET", f"{api}/repos/{repo}/issues/{pr}/comments?per_page={PAGE_SIZE}&page={page}", token)
        if not isinstance(batch, list):
            raise ValueError("Unexpected response while listing comments")
        for item in batch:
            if not isinstance(item, dict):
                continue
            if _first_line(str(item.get("body") or "")) != marker:
                continue
            if _owns(item, identity):
                return item
        if len(batch) < PAGE_SIZE:
            return None
        page += 1


def upsert(body: str, *, api: str, repo: str, pr: str, token: str) -> str:
    marker = body.splitlines()[0] if body else ""
    if not marker.startswith("<!-- traccia-eval:"):
        raise ValueError("Comment body does not start with a traccia-eval marker")
    existing = find_comment(api, repo, pr, token, marker)
    if existing and existing.get("url"):
        _request("PATCH", str(existing["url"]), token, {"body": body})
        return "updated"
    _request("POST", f"{api}/repos/{repo}/issues/{pr}/comments", token, {"body": body})
    return "created"


def main(argv: List[str]) -> int:
    if len(argv) != 2:
        print("usage: comment.py COMMENT_FILE", file=sys.stderr)
        return 2
    with open(argv[1], encoding="utf-8") as handle:
        body = handle.read()
    api = (os.environ.get("GITHUB_API_URL") or "https://api.github.com").rstrip("/")
    repo = os.environ.get("GITHUB_REPOSITORY", "")
    pr = os.environ.get("PR_NUMBER", "")
    token = os.environ.get("TRACCIA_EVAL_GITHUB_TOKEN", "")
    if not (repo and pr and token):
        print("Missing repository, pull request number, or token", file=sys.stderr)
        return 1
    try:
        action = upsert(body, api=api, repo=repo, pr=pr, token=token)
    except urllib.error.HTTPError as exc:
        try:
            exc.read()
        finally:
            exc.close()
        print(f"GitHub API returned {exc.code} {exc.reason}", file=sys.stderr)
        return 1
    except (urllib.error.URLError, OSError, ValueError) as exc:
        print(f"Could not reach the GitHub API: {exc}", file=sys.stderr)
        return 1
    print(f"Pull request comment {action}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
