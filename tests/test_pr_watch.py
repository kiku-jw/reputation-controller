import json
from pathlib import Path

from reputation_controller.pr_watch import read_pr_watch_summary


def test_read_pr_watch_summary_counts_actionable_items(tmp_path: Path):
    state_path = tmp_path / "state.json"
    state_path.write_text(
        json.dumps(
            {
                "checked_at": "2026-06-17T00:00:00Z",
                "all_done": False,
                "results": [
                    {
                        "repo": "acme/widgets",
                        "number": 1,
                        "url": "https://github.com/acme/widgets/pull/1",
                        "title": "Fix widget",
                        "closed": False,
                        "needs_attention": True,
                        "waiting_review": False,
                    },
                    {
                        "repo": "acme/widgets",
                        "number": 2,
                        "url": "https://github.com/acme/widgets/pull/2",
                        "title": "Fix another widget",
                        "closed": False,
                        "needs_attention": False,
                        "waiting_review": True,
                    },
                ],
            }
        )
    )

    summary = read_pr_watch_summary(state_path)

    assert summary["status"] == "ok"
    assert summary["open_count"] == 2
    assert summary["needs_attention_count"] == 1
    assert summary["waiting_review_count"] == 1
    assert summary["needs_attention"][0]["number"] == 1


def test_read_pr_watch_summary_reports_missing_file(tmp_path: Path):
    summary = read_pr_watch_summary(tmp_path / "missing.json")

    assert summary["status"] == "missing"
