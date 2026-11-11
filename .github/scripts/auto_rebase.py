"""Rebase every open pull request onto main after main changes.

Runs from .github/workflows/auto-rebase.yml inside a full clone of the repository, with `gh` signed in.

- A pull request against main is rebased onto the new main.
- A pull request stacked on another pull request's branch is moved onto that branch once the branch is up to date
  with main, so it keeps only its own commits on top. It is left alone while its base branch could not be rebased.
- A branch is only pushed when the rebase had no conflicts. A conflicting branch is left exactly as it was and listed
  in the job summary; GitHub already shows the conflict on the pull request.
- Every push is a force push with lease on the commit that was rebased, so a commit pushed in the meantime is never
  lost: the push is refused and the branch is tried again after the next change to main.
- Pull requests from forks are skipped, since the workflow cannot push to them.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from dataclasses import dataclass

MAIN = os.environ.get("MAIN_BRANCH", "main")
REPOSITORY = os.environ["GITHUB_REPOSITORY"]


@dataclass
class PullRequest:
    number: int
    title: str
    head: str
    base: str


def run(*args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(args, check=check, text=True, capture_output=True)


def git(*args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    return run("git", *args, check=check)


def rev(ref: str) -> str:
    return git("rev-parse", ref).stdout.strip()


def open_pull_requests() -> list[PullRequest]:
    output = run(
        "gh", "pr", "list", "--repo", REPOSITORY, "--state", "open", "--limit", "200",
        "--json", "number,title,headRefName,baseRefName,isCrossRepository",
    ).stdout
    return [
        PullRequest(item["number"], item["title"], item["headRefName"], item["baseRefName"])
        for item in json.loads(output)
        if not item["isCrossRepository"]
    ]


def in_stack_order(pull_requests: list[PullRequest]) -> list[PullRequest]:
    """Pull requests against main first, then each stacked pull request after the one it is based on."""
    by_head = {pr.head: pr for pr in pull_requests}
    ordered: list[PullRequest] = []
    seen: set[str] = set()

    def visit(pr: PullRequest, path: frozenset[str]) -> None:
        if pr.head in seen or pr.head in path:
            return
        parent = by_head.get(pr.base)
        if parent is not None:
            visit(parent, path | {pr.head})
        seen.add(pr.head)
        ordered.append(pr)

    for pr in sorted(pull_requests, key=lambda pr: pr.number):
        visit(pr, frozenset())
    return ordered


def rebase(head_sha: str, onto: str, upstream: str) -> str | None:
    """Replay head_sha's commits after upstream onto `onto`; return the new tip, or None on a conflict."""
    git("checkout", "--quiet", "--detach", head_sha)
    result = git("rebase", "--onto", onto, upstream, check=False)
    if result.returncode != 0:
        git("rebase", "--abort", check=False)
        return None
    return rev("HEAD")


def main() -> int:
    git("fetch", "--quiet", "--prune", "origin", "+refs/heads/*:refs/remotes/origin/*")
    main_sha = rev(f"origin/{MAIN}")

    # Where each branch was before this run and where it is now. Only main and the branches that are up to date with
    # it after this run are in `moved`; a pull request whose base is not in it is left alone.
    moved: dict[str, tuple[str, str]] = {MAIN: (main_sha, main_sha)}
    lines: list[str] = []

    for pr in in_stack_order(open_pull_requests()):
        label = f"#{pr.number} {pr.title} (`{pr.head}` onto `{pr.base}`)"
        head_ref = f"refs/remotes/origin/{pr.head}"
        if git("rev-parse", "--verify", "--quiet", head_ref, check=False).returncode != 0:
            lines.append(f"- Skipped {label}: the branch is gone.")
            continue
        if pr.base not in moved:
            lines.append(f"- Not rebased {label}: `{pr.base}` is not up to date with `{MAIN}`.")
            continue

        head_sha = rev(head_ref)
        old_base, new_base = moved[pr.base]
        if pr.base == MAIN:
            # Rebase everything that is not in main yet. git leaves out commits that main already has.
            upstream = new_base
        else:
            # Only this pull request's own commits: the ones after where its base branch was before this run.
            upstream = git("merge-base", old_base, head_sha).stdout.strip()

        if git("merge-base", "--is-ancestor", new_base, head_sha, check=False).returncode == 0:
            moved[pr.head] = (head_sha, head_sha)
            continue

        new_head = rebase(head_sha, new_base, upstream)
        if new_head is None:
            lines.append(f"- Not rebased {label}: it has conflicts with `{pr.base}`.")
            continue

        push = git(
            "push", f"--force-with-lease=refs/heads/{pr.head}:{head_sha}",
            "origin", f"{new_head}:refs/heads/{pr.head}", check=False,
        )
        if push.returncode != 0:
            reason = push.stderr.strip().splitlines()[-1] if push.stderr.strip() else "the push was refused"
            lines.append(f"- Not rebased {label}: {reason}")
            continue

        moved[pr.head] = (head_sha, new_head)
        lines.append(f"- Rebased {label}.")

    report = "\n".join(lines) if lines else "Every open pull request was already up to date."
    print(report)
    summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary:
        with open(summary, "a", encoding="utf-8") as file:
            file.write(f"## Rebase onto `{MAIN}` at `{main_sha[:7]}`\n\n{report}\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
