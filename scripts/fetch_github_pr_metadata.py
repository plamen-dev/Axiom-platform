#!/usr/bin/env python3
"""Fetch GitHub PR metadata into backfill payload files.

Operational helper (network via `gh` CLI) that writes one JSON payload per
pull request, in the shape `axiom github-import` / `github-import-backfill`
accept. The framework itself stays network-free; this script is the only
place GitHub is contacted.

Usage:
    python scripts/fetch_github_pr_metadata.py \
        --repo plamen-dev/Axiom-platform \
        --out artifacts/github_pr_history
"""

from __future__ import annotations

import argparse
import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path


def _gh_api(path: str) -> list | dict:
    result = subprocess.run(
        ["gh", "api", path],
        capture_output=True,
        text=True,
        check=True,
    )
    return json.loads(result.stdout)


def _list_all_prs(repo: str) -> list[dict]:
    prs: list[dict] = []
    page = 1
    while True:
        batch = _gh_api(f"repos/{repo}/pulls?state=all&per_page=100&page={page}")
        if not batch:
            break
        prs.extend(batch)
        page += 1
    return prs


def _pr_status(pr: dict) -> str:
    if pr.get("merged_at"):
        return "merged"
    if pr.get("draft"):
        return "draft"
    return str(pr.get("state", ""))


def _build_payload(repo: str, pr: dict) -> dict:
    owner, _, name = repo.partition("/")
    number = int(pr["number"])
    commits = _gh_api(f"repos/{repo}/pulls/{number}/commits?per_page=100")
    files = _gh_api(f"repos/{repo}/pulls/{number}/files?per_page=100")
    return {
        "pr": {
            "repository_owner": owner,
            "repository_name": name,
            "repository_pr_number": number,
            "repository_pr_url": pr.get("html_url", ""),
            "title": pr.get("title", ""),
            "description": pr.get("body") or "",
            "author": (pr.get("user") or {}).get("login", ""),
            "branch_name": (pr.get("head") or {}).get("ref", ""),
            "status": _pr_status(pr),
            "merge_commit_sha": pr.get("merge_commit_sha") or "",
            "created_at": pr.get("created_at") or "",
            "updated_at": pr.get("updated_at") or "",
            "merged_at": pr.get("merged_at") or "",
        },
        "commits": [
            {
                "commit_sha": c.get("sha", ""),
                "author": ((c.get("commit") or {}).get("author") or {}).get("name", ""),
                "message": (c.get("commit") or {}).get("message", ""),
                "timestamp": ((c.get("commit") or {}).get("author") or {}).get("date", ""),
            }
            for c in commits
        ],
        "files": [
            {
                "path": f.get("filename", ""),
                "status": f.get("status", ""),
                "additions": int(f.get("additions", 0)),
                "deletions": int(f.get("deletions", 0)),
            }
            for f in files
        ],
        "labels": [
            {
                "name": label.get("name", ""),
                "color": label.get("color", ""),
                "description": label.get("description") or "",
            }
            for label in pr.get("labels", [])
        ],
        "raw_metadata": {
            "source": "gh api",
            "fetched_at": datetime.now(timezone.utc).isoformat(),
        },
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", required=True, help="owner/name")
    parser.add_argument("--out", required=True, help="output directory")
    args = parser.parse_args()

    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)

    prs = _list_all_prs(args.repo)
    for pr in sorted(prs, key=lambda p: int(p["number"])):
        payload = _build_payload(args.repo, pr)
        number = payload["pr"]["repository_pr_number"]
        path = out_dir / f"pr-{number:04d}.json"
        path.write_text(
            json.dumps(payload, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
        print(f"wrote {path}")
    print(f"done: {len(prs)} PRs")


if __name__ == "__main__":
    main()
