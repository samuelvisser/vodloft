"""Keep pull requests from merging into a branch that no longer leads to main.

Runs from .github/workflows/stack-guard.yml for every pull request event, with `gh` signed in.

A pull request may target main, or the branch of another open pull request (a stack). Anything else is a dead end:
once a pull request's base branch was merged or closed, merging into that branch puts the changes nowhere.

- Every open pull request gets a "Stack base" commit status: green when it targets main or an open pull request's
  branch, red otherwise. The pull request of the event and every open pull request on its branch are checked again,
  so a stacked pull request turns red as soon as the one below it is closed.
- When a pull request merges, the pull requests on its branch are moved onto the branch it merged into. GitHub refuses
  this for pull requests in one of its own stacks, which move on their own; those keep a red status until they do.
- When a pull request merged into a branch that is not main and not the branch of an open pull request, its changes
  only reached that branch. A pull request from that branch to main is opened to bring them back, and the merged pull
  request gets a comment that links to it.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from typing import Any

MAIN = os.environ.get("MAIN_BRANCH", "main")
REPOSITORY = os.environ["GITHUB_REPOSITORY"]
STATUS_CONTEXT = "Stack base"


def gh(*args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(("gh", *args), check=check, text=True, capture_output=True)


def api(path: str, *fields: str, method: str = "GET", check: bool = True) -> Any:
    args = ["api", "--method", method, f"repos/{REPOSITORY}/{path}"]
    for field in fields:
        args += ["-f", field]
    result = gh(*args, check=check)
    if result.returncode != 0:
        return None
    return json.loads(result.stdout) if result.stdout.strip() else None


def open_pull_requests() -> list[dict[str, Any]]:
    output = gh(
        "pr", "list", "--repo", REPOSITORY, "--state", "open", "--limit", "200",
        "--json", "number,headRefName,baseRefName,headRefOid,isCrossRepository",
    ).stdout
    return json.loads(output)


def set_status(sha: str, state: str, description: str) -> None:
    api(
        f"statuses/{sha}",
        f"state={state}", f"context={STATUS_CONTEXT}", f"description={description[:140]}",
        method="POST",
    )


def check(pr: dict[str, Any], open_by_head: dict[str, dict[str, Any]]) -> str:
    base = pr["baseRefName"]
    parent = open_by_head.get(base)
    if base == MAIN:
        state, description = "success", f"Targets {MAIN}."
    elif parent is not None and parent["number"] != pr["number"]:
        state, description = "success", f"Stacked on #{parent['number']}."
    else:
        state, description = "failure", (
            f"{base} is not the branch of an open pull request. Merging would not reach {MAIN}; target {MAIN}."
        )
    set_status(pr["headRefOid"], state, description)
    return f"- #{pr['number']} (`{pr['headRefName']}` onto `{base}`): {state}, {description}"


def move_dependents(event_pr: dict[str, Any], lines: list[str]) -> bool:
    """Move the open pull requests on a merged pull request's branch onto the branch it merged into."""
    moved = False
    for pr in open_pull_requests():
        if pr["isCrossRepository"] or pr["baseRefName"] != event_pr["head"]["ref"]:
            continue
        target = event_pr["base"]["ref"]
        result = api(f"pulls/{pr['number']}", f"base={target}", method="PATCH", check=False)
        if result is None:
            lines.append(f"- Could not move #{pr['number']} onto `{target}`; GitHub refused the change.")
        else:
            lines.append(f"- Moved #{pr['number']} onto `{target}`.")
            moved = True
    return moved


def rescue(event_pr: dict[str, Any], open_by_head: dict[str, dict[str, Any]], lines: list[str]) -> bool:
    """Bring back changes that merged into a dead-end branch. Returns False when that could not be done."""
    base = event_pr["base"]["ref"]
    if base == MAIN or base in open_by_head:
        return True
    comparison = api(f"compare/{MAIN}...{base}", check=False)
    if comparison is None:
        lines.append(f"- #{event_pr['number']} merged into `{base}`, which could not be compared with `{MAIN}`.")
        return False
    if comparison["ahead_by"] == 0:
        return True

    number = event_pr["number"]
    body = (
        f"#{number} merged into `{base}` after that branch's own pull request was merged or closed, so its changes "
        f"did not reach `{MAIN}`. This pull request brings them back.\n\n"
        "Opened by the stack guard workflow."
    )
    created = gh(
        "pr", "create", "--repo", REPOSITORY, "--base", MAIN, "--head", base,
        "--title", f"Bring back the changes from #{number}", "--body", body,
        check=False,
    )
    if created.returncode == 0:
        url = created.stdout.strip()
        comment = f"This merged into `{base}`, which no longer leads to `{MAIN}`. {url} brings the changes back."
        lines.append(f"- #{number} merged into dead-end `{base}`; opened {url}.")
        ok = True
    else:
        comment = (
            f"This merged into `{base}`, which no longer leads to `{MAIN}`, so its changes are not in `{MAIN}`. "
            f"Open a pull request from `{base}` to `{MAIN}` to bring them back."
        )
        lines.append(f"- #{number} merged into dead-end `{base}`; could not open a pull request: {created.stderr.strip()}")
        ok = False
    gh("pr", "comment", str(number), "--repo", REPOSITORY, "--body", comment, check=False)
    return ok


def main() -> int:
    with open(os.environ["GITHUB_EVENT_PATH"], encoding="utf-8") as file:
        event = json.load(file)
    event_pr = event["pull_request"]
    lines: list[str] = []
    ok = True

    if event["action"] == "closed" and event_pr["merged"]:
        open_by_head = {pr["headRefName"]: pr for pr in open_pull_requests() if not pr["isCrossRepository"]}
        ok = rescue(event_pr, open_by_head, lines)
        if move_dependents(event_pr, lines):
            gh("workflow", "run", "auto-rebase.yml", "--repo", REPOSITORY, "--ref", MAIN, check=False)

    open_prs = [pr for pr in open_pull_requests() if not pr["isCrossRepository"]]
    open_by_head = {pr["headRefName"]: pr for pr in open_prs}
    for pr in open_prs:
        if pr["number"] == event_pr["number"] or pr["baseRefName"] == event_pr["head"]["ref"]:
            lines.append(check(pr, open_by_head))

    report = "\n".join(lines) if lines else "Nothing to check."
    print(report)
    summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary:
        with open(summary, "a", encoding="utf-8") as file:
            file.write(f"## Stack guard for #{event_pr['number']} ({event['action']})\n\n{report}\n")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
