"""Exercise publication against a disposable local Git remote, never GitHub."""

import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

import publish
import report


class PublishTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.output = self.root / "badges"
        self.env = {**os.environ, "DEFAULT_BRANCH": "main", "GITHUB_REF": "refs/heads/main",
                    "GITHUB_EVENT_NAME": "workflow_dispatch", "GITHUB_REPOSITORY": "owner/repository",
                    "GITHUB_TOKEN": "test-placeholder", "GITHUB_SHA": "a" * 40,
                    "GITHUB_RUN_ID": "100", "GITHUB_RUN_NUMBER": "10", "GITHUB_RUN_ATTEMPT": "1",
                    "GITHUB_SERVER_URL": "https://github.com"}
        self.summary = report.collect(self.root / "absent", {"builds": ["//:a"], "tests": ["//test:a"]}, self.env)
        report.write(self.summary, self.output)

    def test_default_branch_and_manual_event_are_required(self):
        for override in ({"GITHUB_REF": "refs/heads/topic"}, {"DEFAULT_BRANCH": ""},
                         {"GITHUB_EVENT_NAME": "pull_request"}, {"GITHUB_EVENT_NAME": "push"}):
            with self.subTest(override=override), self.assertRaises(ValueError):
                publish.validate(self.output, {**self.env, **override})

    def test_summary_must_match_the_current_run(self):
        self.assertEqual(publish.validate(self.output, self.env), self.summary)
        for override in ({"GITHUB_RUN_ID": "101"}, {"GITHUB_SHA": "b" * 40},
                         {"GITHUB_RUN_NUMBER": "11"}, {"GITHUB_RUN_ATTEMPT": "2"},
                         {"GITHUB_REPOSITORY": "different/repo"}):
            with self.subTest(override=override), self.assertRaises(ValueError):
                publish.validate(self.output, {**self.env, **override})

    def test_symlinked_output_is_rejected(self):
        path = self.output / "builds.svg"
        path.unlink()
        path.symlink_to(self.output / "tests.svg")
        with self.assertRaises(ValueError):
            publish.validate(self.output, self.env)

    def test_token_stays_out_of_urls_and_git_trace_is_disabled(self):
        env = publish.git_environment({**self.env, "GIT_TRACE": "1", "GIT_CURL_VERBOSE": "1",
                                       "GIT_TRACE_CURL": "1", "GIT_CONFIG_COUNT": "99",
                                       "GIT_DIR": "/another/repository/.git"})
        self.assertFalse(any(name.startswith("GIT_TRACE") for name in env))
        self.assertNotIn("GIT_CURL_VERBOSE", env)
        self.assertNotIn("GIT_DIR", env)
        self.assertEqual(env["GIT_CONFIG_GLOBAL"], "/dev/null")
        self.assertEqual(env["GIT_CONFIG_COUNT"], "1")
        self.assertEqual(env["GIT_TERMINAL_PROMPT"], "0")

    def test_isolated_branch_publish_and_out_of_order_guard(self):
        remote = self.root / "remote.git"
        subprocess.run(["git", "init", "--bare", "--quiet", str(remote)], check=True)
        environment = publish.git_environment(self.env)
        self.assertTrue(publish.publish_to_git(self.output, self.summary, str(remote), environment))
        def git(*args):
            return subprocess.check_output(["git", "--git-dir", str(remote), *args], text=True).strip()
        first = git("rev-parse", "ci-status")
        self.assertEqual(set(git("ls-tree", "--name-only", "ci-status").splitlines()), set(report.OUTPUTS))
        self.assertFalse(publish.publish_to_git(self.output, self.summary, str(remote), environment))
        older = json.loads(json.dumps(self.summary))
        older["metadata"]["run_number"] = 9
        self.assertFalse(publish.publish_to_git(self.output, older, str(remote), environment))
        self.assertEqual(git("rev-parse", "ci-status"), first)
        rerun = json.loads(json.dumps(self.summary))
        rerun["metadata"]["run_attempt"] = 2
        report.write(rerun, self.output)
        self.assertTrue(publish.publish_to_git(self.output, rerun, str(remote), environment))
        self.assertNotEqual(git("rev-parse", "ci-status"), first)
        published = json.loads(git("show", "ci-status:summary.json"))
        self.assertEqual(publish.order(published), (10, 2))


if __name__ == "__main__":
    unittest.main()
