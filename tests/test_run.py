"""End-to-end tests of run.sh with fake eval commands and a fake GitHub API."""

import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "tests"))

from fake_github import FakeGitHub  # noqa: E402

RUN = os.path.join(ROOT, "run.sh")
FIXTURES = os.path.join(ROOT, "tests", "fixtures")


def write_summary_command(name, exit_code, output="summary.json"):
    """A shell command that behaves like the CLI: write a fixture, exit with its code."""
    source = os.path.join(FIXTURES, name)
    return f"cp '{source}' '{output}' && exit {exit_code}"


class RunTests(unittest.TestCase):
    def setUp(self):
        self.work = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.work, ignore_errors=True)
        subprocess.run(["git", "init", "-q", self.work], check=True)
        subprocess.run(
            ["git", "-C", self.work, "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-q", "--allow-empty", "-m", "x"],
            check=True,
        )
        self.outputs = os.path.join(self.work, ".outputs")
        self.step = os.path.join(self.work, ".step")

    def run_action(self, command, **env):
        values = {
            "PATH": os.environ["PATH"],
            "HOME": os.environ.get("HOME", self.work),
            "TRACCIA_EVAL_COMMAND": command,
            "GITHUB_OUTPUT": self.outputs,
            "GITHUB_STEP_SUMMARY": self.step,
            "GITHUB_REPOSITORY": "o/r",
            "GITHUB_RUN_ID": "99",
            "GITHUB_WORKFLOW": "Evals",
            "GITHUB_JOB": "eval",
            "GITHUB_REF_NAME": "7/merge",
        }
        values.update({k: v for k, v in env.items() if v is not None})
        result = subprocess.run(["bash", RUN], cwd=self.work, env=values, capture_output=True, text=True)
        outputs = {}
        if os.path.exists(self.outputs):
            with open(self.outputs, encoding="utf-8") as handle:
                outputs = dict(line.split("=", 1) for line in handle.read().splitlines() if "=" in line)
        return result, outputs

    def test_pass_keeps_exit_0(self):
        result, outputs = self.run_action(write_summary_command("quality_gate_pass.json", 0))
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(outputs["label"], "Quality Gate")
        self.assertEqual(outputs["comment_posted"], "false")

    def test_quality_failure_keeps_exit_1(self):
        result, outputs = self.run_action(write_summary_command("regression.json", 1))
        self.assertEqual(result.returncode, 1)
        self.assertEqual(outputs["code"], "regression")

    def test_no_summary_exits_5(self):
        result, outputs = self.run_action("exit 0")
        self.assertEqual(result.returncode, 5)
        self.assertEqual(outputs["code"], "summary_failed")

    def test_unremovable_stale_summary_exits_5(self):
        path = os.path.join(self.work, "summary.json")
        with open(path, "w", encoding="utf-8") as handle:
            handle.write('{"exit_code": 0, "label": "Quality Gate"}\n')
        os.chmod(self.work, 0o500)
        self.addCleanup(os.chmod, self.work, 0o700)
        result, _ = self.run_action("true")
        self.assertEqual(result.returncode, 5, result.stderr)
        with open(path, encoding="utf-8") as handle:
            self.assertIn("Quality Gate", handle.read())

    def test_stale_summary_is_deleted_first(self):
        with open(os.path.join(self.work, "summary.json"), "w", encoding="utf-8") as handle:
            json.dump({"exit_code": 0}, handle)
        result, _ = self.run_action("exit 1")
        self.assertEqual(result.returncode, 5)

    def test_summary_that_disagrees_exits_5(self):
        result, _ = self.run_action(write_summary_command("quality_gate_pass.json", 1))
        self.assertEqual(result.returncode, 5)

    def test_eval_command_cannot_see_the_github_token(self):
        secret = "ghs_test_secret_value"
        command = 'printf "%s" "${TRACCIA_EVAL_GITHUB_TOKEN-UNSET}" > seen.txt; ' + write_summary_command(
            "execution_only.json", 0
        )
        with FakeGitHub() as fake:
            result, outputs = self.run_action(
                command,
                GITHUB_API_URL=fake.url,
                PR_NUMBER="7",
                TRACCIA_EVAL_GITHUB_TOKEN=secret,
            )
        self.assertEqual(result.returncode, 0, result.stderr)
        with open(os.path.join(self.work, "seen.txt"), encoding="utf-8") as handle:
            self.assertEqual(handle.read(), "UNSET")
        self.assertNotIn(secret, result.stdout + result.stderr)
        self.assertEqual(outputs["comment_posted"], "true")
        self.assertNotIn(secret, fake.comments[0]["body"])

    def test_git_metadata_reaches_the_command(self):
        command = 'echo "$TRACCIA_GIT_CHECKOUT_SHA $TRACCIA_PR_NUMBER $TRACCIA_GIT_REPOSITORY" > meta.txt; ' + write_summary_command(
            "execution_only.json", 0
        )
        result, _ = self.run_action(command, PR_NUMBER="7")
        self.assertEqual(result.returncode, 0, result.stderr)
        with open(os.path.join(self.work, "meta.txt"), encoding="utf-8") as handle:
            sha, pr, repo = handle.read().split()
        self.assertEqual(len(sha), 40)
        self.assertEqual((pr, repo), ("7", "o/r"))

    def test_values_set_by_the_job_win(self):
        command = 'echo "$TRACCIA_GIT_HEAD_REF" > ref.txt; ' + write_summary_command("execution_only.json", 0)
        self.run_action(command, TRACCIA_GIT_HEAD_REF="custom", GITHUB_HEAD_REF="from-github")
        with open(os.path.join(self.work, "ref.txt"), encoding="utf-8") as handle:
            self.assertEqual(handle.read().strip(), "custom")

    def test_working_directory_and_custom_summary_path(self):
        os.mkdir(os.path.join(self.work, "evals"))
        command = write_summary_command("execution_only.json", 0, output="out/result.json")
        result, outputs = self.run_action(
            "mkdir -p out && " + command, TRACCIA_EVAL_WORKING_DIRECTORY="evals", TRACCIA_EVAL_SUMMARY="out/result.json"
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(outputs["summary_path"].endswith("evals/out/result.json"))

    def test_missing_working_directory_exits_5(self):
        result, _ = self.run_action("exit 0", TRACCIA_EVAL_WORKING_DIRECTORY="nope")
        self.assertEqual(result.returncode, 5)

    def test_comment_is_posted_and_then_updated(self):
        with FakeGitHub() as fake:
            env = {"GITHUB_API_URL": fake.url, "PR_NUMBER": "7", "TRACCIA_EVAL_GITHUB_TOKEN": "t"}
            result, outputs = self.run_action(write_summary_command("regression.json", 1), **env)
            self.assertEqual(result.returncode, 1, result.stderr)
            self.assertEqual(outputs["comment_posted"], "true")
            self.run_action(write_summary_command("quality_gate_pass.json", 0), **env)
            self.assertEqual(len(fake.comments), 1)
            body = fake.comments[0]["body"]
            self.assertTrue(body.startswith("<!-- traccia-eval:Evals-eval-7/merge -->"))
            self.assertIn("Quality Gate", body)
            self.assertIn("[View run](https://github.com/o/r/actions/runs/99)", body)

    def test_comment_failure_does_not_change_the_result(self):
        with FakeGitHub(fail_with=403) as fake:
            env = {"GITHUB_API_URL": fake.url, "PR_NUMBER": "7", "TRACCIA_EVAL_GITHUB_TOKEN": "t"}
            result, outputs = self.run_action(write_summary_command("quality_gate_pass.json", 0), **env)
        self.assertEqual(result.returncode, 0)
        self.assertEqual(outputs["comment_posted"], "false")
        with open(self.step, encoding="utf-8") as handle:
            self.assertIn("comment was not posted", handle.read())

    def test_comment_can_be_turned_off(self):
        with FakeGitHub() as fake:
            env = {"GITHUB_API_URL": fake.url, "PR_NUMBER": "7", "TRACCIA_EVAL_GITHUB_TOKEN": "t", "TRACCIA_EVAL_COMMENT": "false"}
            self.run_action(write_summary_command("quality_gate_pass.json", 0), **env)
            self.assertEqual(fake.requests, [])


if __name__ == "__main__":
    unittest.main()
