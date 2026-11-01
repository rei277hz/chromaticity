#!/usr/bin/env python3
"""Publish only generated manual-run badges on the dedicated ci-status branch."""

import argparse
import base64
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile

from report import OUTPUTS


BRANCH = "ci-status"


def order(summary):
    if not isinstance(summary, dict) or not isinstance(summary.get("metadata"), dict):
        raise ValueError("Invalid published status metadata")
    metadata = summary.get("metadata", {})
    values = (metadata.get("run_number"), metadata.get("run_attempt"))
    if any(type(value) is not int or value <= 0 for value in values):
        raise ValueError("Published status needs positive run number and attempt")
    return values


def validate(directory, env):
    """Enforce the publication boundary independently of workflow conditions."""
    branch = env.get("DEFAULT_BRANCH", "")
    if not branch or env.get("GITHUB_REF") != f"refs/heads/{branch}":
        raise ValueError("Badges may only be published from the default branch")
    if env.get("GITHUB_EVENT_NAME") != "workflow_dispatch":
        raise ValueError("Badges may only be published by a manual workflow")
    repository = env.get("GITHUB_REPOSITORY", "")
    if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repository):
        raise ValueError("Invalid GitHub repository")
    if env.get("GITHUB_SERVER_URL", "https://github.com") != "https://github.com":
        raise ValueError("This publisher is configured for github.com")
    if not env.get("GITHUB_TOKEN"):
        raise ValueError("GITHUB_TOKEN is required for badge publication")
    for name in OUTPUTS:
        path = directory / name
        if path.is_symlink() or not path.is_file() or path.stat().st_size > 1_000_000:
            raise ValueError(f"Missing, linked, or oversized badge output: {name}")
    summary = json.loads((directory / "summary.json").read_text())
    if not isinstance(summary, dict) or summary.get("schema") != 1:
        raise ValueError("Invalid status summary schema")
    metadata = summary.get("metadata")
    if not isinstance(metadata, dict):
        raise ValueError("Missing status metadata")
    for name, variable in (("repository", "GITHUB_REPOSITORY"), ("commit", "GITHUB_SHA"),
                           ("run_id", "GITHUB_RUN_ID")):
        if not env.get(variable) or str(metadata.get(name)) != env[variable]:
            raise ValueError(f"Status {name} does not match this workflow run")
    if not re.fullmatch(r"[0-9a-f]{40}", metadata["commit"]):
        raise ValueError("Invalid status commit")
    if not re.fullmatch(r"[0-9]+", metadata["run_id"]):
        raise ValueError("Invalid workflow run ID")
    expected_order = (int(env.get("GITHUB_RUN_NUMBER", "0")), int(env.get("GITHUB_RUN_ATTEMPT", "0")))
    if order(summary) != expected_order:
        raise ValueError("Status run order does not match this workflow run")
    expected_url = f'https://github.com/{repository}/actions/runs/{metadata["run_id"]}'
    if metadata.get("run_url") != expected_url:
        raise ValueError("Status run URL does not match this workflow run")
    return summary


def newer(incoming, current):
    order(current)
    if current.get("schema") != 1:
        raise ValueError("Invalid existing status schema")
    if incoming["metadata"]["repository"] != current.get("metadata", {}).get("repository"):
        raise ValueError("Existing status belongs to a different repository")
    return order(incoming) > order(current)


def git_environment(env):
    # In particular, an inherited GIT_DIR/GIT_WORK_TREE must not redirect writes
    # away from the disposable checkout, and user URL rewrites must not see tokens.
    clean = {key: value for key, value in env.items() if not key.startswith("GIT_")}
    # Credentials live in the child environment, never in argv, URLs, files, or output.
    authorization = base64.b64encode(f'x-access-token:{env["GITHUB_TOKEN"]}'.encode()).decode()
    clean.update({"GIT_CONFIG_COUNT": "1", "GIT_CONFIG_KEY_0": "http.https://github.com/.extraheader",
                  "GIT_CONFIG_VALUE_0": "AUTHORIZATION: basic " + authorization,
                  "GIT_CONFIG_GLOBAL": "/dev/null", "GIT_CONFIG_SYSTEM": "/dev/null",
                  "GIT_TERMINAL_PROMPT": "0"})
    return clean


def publish_to_git(directory, summary, remote, env):
    """Use an isolated checkout and a normal fast-forward push; never force-push."""
    with tempfile.TemporaryDirectory(prefix="perceptual-grade-badges-") as temporary:
        checkout = Path(temporary)
        def git(*args):
            process = subprocess.run(["git", *args], cwd=checkout, env=env, text=True,
                                     stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            if process.returncode:
                # Avoid emitting credentials from any inherited Git diagnostic settings.
                raise RuntimeError(f"Badge publication git {args[0]} failed (exit {process.returncode})")
            return process.stdout
        git("init", "--quiet")
        git("config", "user.name", "github-actions[bot]")
        git("config", "user.email", "41898282+github-actions[bot]@users.noreply.github.com")
        git("config", "commit.gpgsign", "false")
        git("config", "core.hooksPath", "/dev/null")
        git("remote", "add", "origin", remote)
        exists = bool(git("ls-remote", "--heads", "origin", f"refs/heads/{BRANCH}").strip())
        if exists:
            git("fetch", "--quiet", "--depth=1", "origin", f"refs/heads/{BRANCH}")
            git("checkout", "--quiet", "-b", BRANCH, "FETCH_HEAD")
            current_path = checkout / "summary.json"
            if not current_path.is_file() or current_path.is_symlink():
                raise ValueError("Existing status branch is missing its run-order record")
            current = json.loads(current_path.read_text())
            if not newer(summary, current):
                print("Status already contains this run or a newer manual run; publication skipped.")
                return False
            git("rm", "--quiet", "-r", "--ignore-unmatch", ".")
        else:
            git("checkout", "--quiet", "--orphan", BRANCH)
        for name in OUTPUTS:
            shutil.copyfile(directory / name, checkout / name)
        git("add", "--", *OUTPUTS)
        metadata = summary["metadata"]
        git("commit", "--quiet", "-m", f'Update Linux status for run {metadata["run_number"]}.{metadata["run_attempt"]}')
        git("push", "--quiet", "origin", f"HEAD:refs/heads/{BRANCH}")
    print(f"Published manual build/test badges to {BRANCH}.")
    return True


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--directory", type=Path, required=True)
    args = parser.parse_args()
    summary = validate(args.directory, os.environ)
    remote = f'https://github.com/{os.environ["GITHUB_REPOSITORY"]}.git'
    publish_to_git(args.directory, summary, remote, git_environment(os.environ))


if __name__ == "__main__":
    try:
        main()
    except (OSError, ValueError, RuntimeError) as error:
        raise SystemExit(str(error)) from error
