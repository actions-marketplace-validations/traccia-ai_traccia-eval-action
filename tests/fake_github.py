"""A tiny in-process stand-in for the GitHub issue comments API."""

from __future__ import annotations

import json
import re
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Dict, List, Optional
from urllib.parse import parse_qs, urlparse


class FakeGitHub:
    def __init__(
        self,
        comments: Optional[List[Dict[str, Any]]] = None,
        fail_with: Optional[int] = None,
        user_status: Optional[int] = None,
    ):
        self.comments: List[Dict[str, Any]] = list(comments or [])
        self.fail_with = fail_with
        self.user_status = user_status
        self.login = "github-actions[bot]"
        self.requests: List[Dict[str, Any]] = []
        self._server = ThreadingHTTPServer(("127.0.0.1", 0), self._handler())
        self.url = f"http://127.0.0.1:{self._server.server_port}"
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)

    def __enter__(self) -> "FakeGitHub":
        self._thread.start()
        return self

    def __exit__(self, *exc: Any) -> None:
        self._server.shutdown()
        self._server.server_close()

    def add_comments(self, count: int, body: str = "unrelated") -> None:
        for _ in range(count):
            self._new(body)

    def _new(self, body: str, user: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        number = len(self.comments) + 1
        login = str((user or {}).get("login") or self.login)
        comment = {
            "id": number,
            "body": body,
            "url": f"{self.url}/repos/o/r/issues/comments/{number}",
            "user": {"login": login, "type": "Bot" if login.endswith("[bot]") else "User"},
        }
        if login == self.login:
            comment["performed_via_github_app"] = {"slug": "github-actions"}
        self.comments.append(comment)
        return comment

    def _handler(self):
        fake = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args: Any) -> None:  # keep test output quiet
                pass

            def _send(self, code: int, payload: Any) -> None:
                raw = json.dumps(payload).encode()
                self.send_response(code)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(raw)))
                self.end_headers()
                self.wfile.write(raw)

            def _body(self) -> Any:
                length = int(self.headers.get("Content-Length") or 0)
                return json.loads(self.rfile.read(length) or b"null")

            def _record(self, payload: Any = None) -> None:
                fake.requests.append(
                    {"method": self.command, "path": self.path, "auth": self.headers.get("Authorization"), "body": payload}
                )

            def do_GET(self) -> None:
                self._record()
                path = urlparse(self.path).path
                if path.rstrip("/").endswith("/user") and "/repos/" not in path:
                    if fake.user_status:
                        return self._send(fake.user_status, {"message": "Resource not accessible by integration"})
                    if fake.fail_with:
                        return self._send(fake.fail_with, {"message": "nope"})
                    return self._send(200, {"login": fake.login, "type": "Bot"})
                if fake.fail_with:
                    return self._send(fake.fail_with, {"message": "nope"})
                query = parse_qs(urlparse(self.path).query)
                size = int(query.get("per_page", ["30"])[0])
                page = int(query.get("page", ["1"])[0])
                self._send(200, fake.comments[(page - 1) * size : page * size])

            def do_POST(self) -> None:
                payload = self._body()
                self._record(payload)
                if fake.fail_with:
                    return self._send(fake.fail_with, {"message": "nope"})
                self._send(201, fake._new(payload["body"]))

            def do_PATCH(self) -> None:
                payload = self._body()
                self._record(payload)
                match = re.search(r"/comments/(\d+)$", self.path)
                comment = fake.comments[int(match.group(1)) - 1]
                comment["body"] = payload["body"]
                self._send(200, comment)

        return Handler
