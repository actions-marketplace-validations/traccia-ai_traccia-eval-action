import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))
sys.path.insert(0, os.path.join(ROOT, "tests"))

import comment  # noqa: E402
from fake_github import FakeGitHub  # noqa: E402

MARKER = "<!-- traccia-eval:support -->"


def upsert(fake, body):
    return comment.upsert(body, api=fake.url, repo="o/r", pr="7", token="t0ken")


class UpsertTests(unittest.TestCase):
    def test_creates_when_absent(self):
        with FakeGitHub() as fake:
            self.assertEqual(upsert(fake, f"{MARKER}\nfirst"), "created")
            self.assertEqual(len(fake.comments), 1)
            self.assertEqual(fake.requests[-1]["auth"], "Bearer t0ken")

    def test_updates_existing_comment(self):
        with FakeGitHub() as fake:
            upsert(fake, f"{MARKER}\nfirst")
            self.assertEqual(upsert(fake, f"{MARKER}\nsecond"), "updated")
            self.assertEqual(len(fake.comments), 1)
            self.assertIn("second", fake.comments[0]["body"])

    def test_finds_a_comment_past_the_first_page(self):
        with FakeGitHub() as fake:
            fake.add_comments(150)
            fake._new(f"{MARKER}\nold")
            self.assertEqual(upsert(fake, f"{MARKER}\nnew"), "updated")
            self.assertEqual(len(fake.comments), 151)
            pages = [r["path"] for r in fake.requests if r["method"] == "GET" and "comments" in r["path"]]
            self.assertEqual(len(pages), 2)

    def test_other_keys_get_their_own_comment(self):
        with FakeGitHub() as fake:
            upsert(fake, f"{MARKER}\nsupport")
            upsert(fake, "<!-- traccia-eval:billing -->\nbilling")
            self.assertEqual(len(fake.comments), 2)

    def test_body_without_marker_is_refused(self):
        with FakeGitHub() as fake:
            with self.assertRaises(ValueError):
                upsert(fake, "no marker")
            self.assertEqual(fake.requests, [])

    def test_installation_token_updates_the_actions_bot_comment(self):
        with FakeGitHub(user_status=403) as fake:
            fake._new(f"{MARKER}\nold")
            fake._new(f"{MARKER}\nquoted", user={"login": "contributor"})
            self.assertEqual(upsert(fake, f"{MARKER}\nnew"), "updated")
            self.assertEqual(len(fake.comments), 2)
            self.assertIn("new", fake.comments[0]["body"])
            self.assertIn("quoted", fake.comments[1]["body"])

    def test_quoted_marker_and_other_authors_are_left_alone(self):
        with FakeGitHub() as fake:
            fake._new(f"quoting the marker\n{MARKER}\n", user={"login": "contributor"})
            fake._new(f"{MARKER}\nnot our comment", user={"login": "contributor"})
            self.assertEqual(upsert(fake, f"{MARKER}\nours"), "created")
            self.assertEqual(len(fake.comments), 3)
            self.assertIn("quoting the marker", fake.comments[0]["body"])
            self.assertIn("not our comment", fake.comments[1]["body"])
            self.assertTrue(fake.comments[2]["body"].startswith(MARKER))


class MainTests(unittest.TestCase):
    def setUp(self):
        self.path = os.path.join(os.path.dirname(__file__), "_comment.md")
        with open(self.path, "w", encoding="utf-8") as handle:
            handle.write(f"{MARKER}\nbody\n")
        self.addCleanup(os.unlink, self.path)

    def run_main(self, fake, **env):
        values = {"GITHUB_API_URL": fake.url, "GITHUB_REPOSITORY": "o/r", "PR_NUMBER": "7", "TRACCIA_EVAL_GITHUB_TOKEN": "t"}
        values.update(env)
        old = {k: os.environ.get(k) for k in values}
        os.environ.update({k: v for k, v in values.items() if v is not None})
        for key, value in values.items():
            if value is None:
                os.environ.pop(key, None)
        try:
            return comment.main(["comment.py", self.path])
        finally:
            for key, value in old.items():
                if value is None:
                    os.environ.pop(key, None)
                else:
                    os.environ[key] = value

    def test_success(self):
        with FakeGitHub() as fake:
            self.assertEqual(self.run_main(fake), 0)

    def test_permission_error_returns_1(self):
        with FakeGitHub(fail_with=403) as fake:
            self.assertEqual(self.run_main(fake), 1)

    def test_missing_token_returns_1(self):
        with FakeGitHub() as fake:
            self.assertEqual(self.run_main(fake, TRACCIA_EVAL_GITHUB_TOKEN=None), 1)
            self.assertEqual(fake.requests, [])


if __name__ == "__main__":
    unittest.main()
