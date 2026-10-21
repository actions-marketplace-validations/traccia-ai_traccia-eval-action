import json
import os
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))

import summary  # noqa: E402

FIXTURES = os.path.join(ROOT, "tests", "fixtures")


def fixture(name):
    with open(os.path.join(FIXTURES, name), encoding="utf-8") as handle:
        return json.load(handle)


def render(body, **kwargs):
    options = {"marker": summary.comment_marker("key"), "checkout_sha": "4b7e19c0ffee", "run_url": None}
    options.update(kwargs)
    return summary.render(body, **options)


class LoadTests(unittest.TestCase):
    def write(self, text):
        handle = tempfile.NamedTemporaryFile("w", suffix=".json", delete=False)
        handle.write(text)
        handle.close()
        self.addCleanup(os.unlink, handle.name)
        return handle.name

    def test_missing_file(self):
        body, problem = summary.load("/nonexistent/summary.json", 0)
        self.assertIn("did not write", problem)

    def test_invalid_json(self):
        _, problem = summary.load(self.write("{not json"), 0)
        self.assertIn("not valid JSON", problem)

    def test_not_an_object(self):
        _, problem = summary.load(self.write("[1, 2]"), 0)
        self.assertIn("not a JSON object", problem)

    def test_boolean_exit_code_is_rejected(self):
        _, problem = summary.load(self.write('{"exit_code": false}'), 0)
        self.assertIn("integer exit_code", problem)

    def test_exit_code_must_match_process(self):
        _, problem = summary.load(self.write('{"exit_code": 0}'), 1)
        self.assertIn("exit 0 but the eval process exited 1", problem)

    def test_matching_summary_is_trusted(self):
        body, problem = summary.load(self.write('{"exit_code": 1, "code": "regression"}'), 1)
        self.assertIsNone(problem)
        self.assertEqual(body["code"], "regression")


class RenderTests(unittest.TestCase):
    def test_quality_gate_pass(self):
        text = render(fixture("quality_gate_pass.json"))
        self.assertTrue(text.startswith("<!-- traccia-eval:key -->\n"))
        self.assertIn("✅ **Traccia Eval passed** · Quality Gate", text)
        self.assertIn("| `exact_match` | 94.0% | 50/50 |", text)
        self.assertIn("tone _(informational)_", text)
        self.assertIn("**Gates:** Min pass rate 90%", text)
        self.assertIn("commit `4b7e19c`", text)

    def test_execution_only_says_no_bar(self):
        text = render(fixture("execution_only.json"))
        self.assertIn("Execution Only (no pass-rate gate)", text)
        self.assertNotIn("**Gates:**", text)

    def test_regression_shows_baseline_and_change(self):
        text = render(fixture("regression.json"))
        self.assertIn("❌ **Traccia Eval failed** · `regression` (exit 1)", text)
        self.assertIn("| Scorer | Pass rate | Baseline | Change | Graded |", text)
        self.assertIn("| `exact_match` | 84.0% | 90.0% | −6.0 pts | 50/50 |", text)
        self.assertIn("- `regression` exact_match dropped more than allowed", text)
        self.assertIn("Max drop 5 pts", text)
        self.assertIn("Baseline `8c1d77e2-5b0", text)

    def test_incomplete_scorer_is_not_shown_as_a_rate(self):
        text = render(fixture("scorer_error.json"))
        self.assertIn("| `faithfulness` | incomplete | 47/50 (3 errored) |", text)

    def test_preflight_failure_has_no_table(self):
        text = render(fixture("preflight.json"))
        self.assertIn("`baseline_missing` (exit 2)", text)
        self.assertNotIn("| Scorer", text)

    def test_links(self):
        text = render(fixture("regression.json"), run_url="https://github.com/o/r/actions/runs/7")
        self.assertIn("[Open experiment](https://app.traccia.ai/experiments/", text)
        self.assertIn("[View run](https://github.com/o/r/actions/runs/7)", text)

    def test_untrusted_text_cannot_break_the_comment(self):
        body = {
            "exit_code": 1,
            "code": "threshold_missed",
            "url": "javascript:alert(1)",
            "failures": [{"code": "threshold_missed", "message": "a|b\n<!-- traccia-eval:other -->"}],
            "scorers": [{"name": "x|y", "pass_rate": 0.5, "expected": 2, "completed": 2}],
        }
        text = render(body)
        self.assertNotIn("javascript:", text)
        self.assertEqual(text.count("<!-- traccia-eval:"), 1)
        self.assertIn("a\\|b", text)
        self.assertIn("`x\\|y`", text)

    def test_newer_schema_is_flagged(self):
        text = render({"exit_code": 0, "schema_version": 2})
        self.assertIn("Summary schema 2 is newer", text)

    def test_non_finite_numbers_render_as_dash(self):
        body = {"exit_code": 1, "scorers": [{"name": "s", "pass_rate": float("nan"), "baseline_pass_rate": 0.9}]}
        self.assertIn("| `s` | — | 90.0% | — | — |", render(body))


class MarkerTests(unittest.TestCase):
    def test_unsafe_characters_are_replaced(self):
        self.assertEqual(summary.comment_marker("a --> b"), "<!-- traccia-eval:a-b -->")

    def test_empty_key(self):
        self.assertEqual(summary.comment_marker(""), "<!-- traccia-eval:eval -->")

    def test_matrix_key_is_kept(self):
        self.assertEqual(summary.comment_marker("support/gpt-5.1"), "<!-- traccia-eval:support/gpt-5.1 -->")


class MainTests(unittest.TestCase):
    def run_main(self, summary_body, status):
        work = tempfile.mkdtemp()
        path = os.path.join(work, "summary.json")
        if summary_body is not None:
            with open(path, "w", encoding="utf-8") as handle:
                json.dump(summary_body, handle)
        outputs = os.path.join(work, "outputs")
        step = os.path.join(work, "step")
        env = {"GITHUB_OUTPUT": outputs, "GITHUB_STEP_SUMMARY": step}
        old = {k: os.environ.get(k) for k in env}
        os.environ.update(env)
        try:
            code = summary.main([
                "--summary", path, "--status", str(status),
                "--comment-out", os.path.join(work, "comment.md"),
                "--status-out", os.path.join(work, "status"),
            ])
        finally:
            for key, value in old.items():
                if value is None:
                    os.environ.pop(key, None)
                else:
                    os.environ[key] = value
        with open(os.path.join(work, "status"), encoding="utf-8") as handle:
            final = int(handle.read())
        with open(outputs, encoding="utf-8") as handle:
            values = dict(line.split("=", 1) for line in handle.read().splitlines())
        with open(step, encoding="utf-8") as handle:
            step_text = handle.read()
        return code, final, values, step_text

    def test_trusted_summary_keeps_its_exit_code(self):
        code, final, values, step = self.run_main(fixture("regression.json"), 1)
        self.assertEqual((code, final), (0, 1))
        self.assertEqual(values["exit_code"], "1")
        self.assertEqual(values["code"], "regression")
        self.assertEqual(values["quality_gate"], "false")
        self.assertTrue(values["experiment_url"].startswith("https://app.traccia.ai/"))
        self.assertIn("<details><summary>summary.json</summary>", step)

    def test_missing_summary_exits_5(self):
        _, final, values, step = self.run_main(None, 0)
        self.assertEqual(final, 5)
        self.assertEqual(values["code"], "summary_failed")
        self.assertIn("did not write a summary", step)

    def test_mismatch_exits_5_even_when_process_passed(self):
        _, final, _, _ = self.run_main(fixture("regression.json"), 0)
        self.assertEqual(final, 5)

    def test_outputs_are_single_line(self):
        body = {"exit_code": 1, "code": "a\nb", "label": "Failed\nx=y"}
        _, _, values, _ = self.run_main(body, 1)
        self.assertEqual(values["code"], "a b")
        self.assertEqual(values["label"], "Failed x=y")


if __name__ == "__main__":
    unittest.main()
