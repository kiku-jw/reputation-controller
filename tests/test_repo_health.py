import urllib.error

from reputation_controller.repo_health import (
    ScorecardClient,
    repo_health_from_scorecard,
)


class FakeHttp:
    def __init__(self, payload):
        self.payload = payload
        self.urls = []

    def get_json(self, url: str):
        self.urls.append(url)
        return self.payload


def scorecard_payload(checks):
    return {
        "date": "2026-06-15",
        "repo": {"commit": "abc123"},
        "score": 4.6,
        "checks": checks,
    }


def check(name, score, reason="reason"):
    return {
        "name": name,
        "score": score,
        "reason": reason,
        "documentation": {"url": f"https://example.com/{name}"},
        "details": ["detail"],
    }


def test_repo_health_from_scorecard_selects_advisory_reasons():
    report = repo_health_from_scorecard(
        "fossasia/visdom",
        "https://api.scorecard.dev/projects/github.com/fossasia/visdom",
        scorecard_payload(
            [
                check("Maintained", 10),
                check("CI-Tests", 0),
                check("Code-Review", 7),
                check("License", 10),
                check("Branch-Protection", 1),
                check("Fuzzing", 0),
            ]
        ),
    )

    assert report.status == "downgrade"
    assert report.advisory_reasons == ["weak_ci_tests", "weak_branch_protection"]
    assert [item.name for item in report.selected_checks] == [
        "Maintained",
        "CI-Tests",
        "Code-Review",
        "License",
        "Branch-Protection",
    ]
    assert report.to_dict()["selected_checks"][0]["details"] == ["detail"]


def test_scorecard_client_returns_error_report_on_lookup_failure():
    class BrokenHttp:
        def get_json(self, url: str):
            raise RuntimeError("network down")

    report = ScorecardClient(http=BrokenHttp()).repo_health("owner/repo")

    assert report.status == "error"
    assert report.advisory_reasons == ["scorecard_lookup_failed"]
    assert "network down" in report.error


def test_scorecard_client_marks_missing_scorecard_result():
    class MissingHttp:
        def get_json(self, url: str):
            raise urllib.error.HTTPError(
                url,
                404,
                "Not Found",
                hdrs=None,
                fp=None,
            )

    report = ScorecardClient(http=MissingHttp()).repo_health("owner/repo")

    assert report.status == "error"
    assert report.advisory_reasons == ["scorecard_not_found"]


def test_scorecard_client_builds_scorecard_url():
    http = FakeHttp(scorecard_payload([check("Maintained", 10)]))
    report = ScorecardClient(http=http).repo_health("owner/repo")

    assert report.status == "pass"
    assert http.urls == ["https://api.scorecard.dev/projects/github.com/owner/repo"]
