"""Publication du commentaire sur la pull request via l'API GitHub."""
from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from typing import Any

from .render import MARKER

API = "https://api.github.com"


def _token() -> str:
    token = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN") or ""
    if not token:
        raise RuntimeError("GITHUB_TOKEN absent : impossible de commenter la PR")
    return token


def _request(method: str, url: str, payload: dict | None = None) -> Any:
    data = json.dumps(payload).encode() if payload is not None else None
    request = urllib.request.Request(url, data=data, method=method, headers={
        "Authorization": f"Bearer {_token()}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": "pr-reviewer",
        "Content-Type": "application/json",
    })
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            body = response.read()
            return json.loads(body) if body else {}
    except urllib.error.HTTPError as exc:
        raise RuntimeError(f"GitHub HTTP {exc.code} : "
                           f"{exc.read().decode('utf-8', 'replace')[:200]}") from exc


def find_existing_comment(repo: str, pr_number: int) -> int | None:
    comments = _request("GET", f"{API}/repos/{repo}/issues/{pr_number}/comments?per_page=100")
    for comment in comments if isinstance(comments, list) else []:
        if MARKER in (comment.get("body") or ""):
            return int(comment["id"])
    return None


def post_comment(repo: str, pr_number: int, body: str, dry_run: bool = False) -> dict[str, Any]:
    """Publie (ou met à jour) le commentaire. Une seule revue par PR : mise à jour."""
    if dry_run:
        return {"dry_run": True, "repo": repo, "pr": pr_number, "body": body}
    existing = find_existing_comment(repo, pr_number)
    if existing:
        result = _request("PATCH", f"{API}/repos/{repo}/issues/comments/{existing}",
                          {"body": body})
        return {"updated": True, "id": result.get("id"), "url": result.get("html_url")}
    result = _request("POST", f"{API}/repos/{repo}/issues/{pr_number}/comments",
                      {"body": body})
    return {"created": True, "id": result.get("id"), "url": result.get("html_url")}


def fetch_pr_diff(repo: str, pr_number: int) -> str:
    """Récupère le diff de la PR (Accept: application/vnd.github.diff)."""
    request = urllib.request.Request(
        f"{API}/repos/{repo}/pulls/{pr_number}",
        headers={"Authorization": f"Bearer {_token()}",
                 "Accept": "application/vnd.github.diff",
                 "User-Agent": "pr-reviewer"})
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            return response.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as exc:
        raise RuntimeError(f"GitHub HTTP {exc.code}") from exc
