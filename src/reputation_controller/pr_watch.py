"""Read-only PR watch state summarization."""

from __future__ import annotations

import json
from pathlib import Path


def read_pr_watch_summary(path: Path) -> dict:
    if not path.exists():
        return {
            "status": "missing",
            "path": str(path),
        }
    try:
        data = json.loads(path.read_text())
    except json.JSONDecodeError:
        return {
            "status": "invalid_json",
            "path": str(path),
        }
    results = data.get("results", [])
    open_items = [item for item in results if not item.get("closed")]
    needs_attention = [item for item in results if item.get("needs_attention")]
    waiting_review = [item for item in results if item.get("waiting_review")]
    return {
        "status": "ok",
        "path": str(path),
        "checked_at": data.get("checked_at", ""),
        "all_done": bool(data.get("all_done", False)),
        "open_count": len(open_items),
        "needs_attention_count": len(needs_attention),
        "waiting_review_count": len(waiting_review),
        "needs_attention": [_pr_summary(item) for item in needs_attention],
        "waiting_review": [_pr_summary(item) for item in waiting_review],
    }


def _pr_summary(item: dict) -> dict:
    return {
        "repo": item.get("repo", ""),
        "number": item.get("number", 0),
        "url": item.get("url", ""),
        "title": item.get("title", ""),
        "review_decision": item.get("review_decision", ""),
        "merge_state_status": item.get("merge_state_status", ""),
    }
