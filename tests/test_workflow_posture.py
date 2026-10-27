# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Mike Gigante <mike.gigante@gmail.com>
"""Where the workflow runs a pull request from a fork.

The runner is chosen by the repository variable RUNS_ON, which may name self-hosted machines. A pull
request from a fork runs code its author wrote, so it always runs on a GitHub-hosted runner, whatever
RUNS_ON says.
"""

from __future__ import annotations

from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent
FORK_GUARD = (
    "${{ (github.event_name == 'pull_request' && github.event.pull_request.head.repo.full_name != "
    "github.repository) && 'ubuntu-latest' || fromJSON(vars.RUNS_ON || '\"ubuntu-latest\"') }}"
)


def assert_forks_run_on_hosted_runners(workflow: Path) -> None:
    jobs = yaml.safe_load(workflow.read_text(encoding="utf-8"))["jobs"]
    assert jobs
    for name, job in jobs.items():
        assert job["runs-on"] == FORK_GUARD, (workflow, name, job["runs-on"])


def test_the_workflow_runs_fork_prs_on_hosted_runners() -> None:
    assert_forks_run_on_hosted_runners(REPO_ROOT / ".github" / "workflows" / "pir-gate.yml")
