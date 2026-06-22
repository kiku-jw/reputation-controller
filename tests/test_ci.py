from reputation_controller.ci import classify_checks
from reputation_controller.github import CheckRun


def test_classifies_github_actions_success_while_ignoring_sourcery_skip():
    verdict = classify_checks(
        [
            CheckRun(name="Functional Test (Polling)", state="pass"),
            CheckRun(name="Visual Regression Test", state="pass"),
            CheckRun(
                name="Sourcery review", state="skipping", link="https://sourcery.ai"
            ),
        ]
    )

    assert verdict.status == "pass"
    assert verdict.actionable_failures == []
    assert verdict.external_skips == ["Sourcery review"]


def test_classifies_actionable_failure_and_pending_checks():
    verdict = classify_checks(
        [
            CheckRun(name="Functional Test (Polling)", state="fail"),
            CheckRun(name="Visual Regression Test", state="pending"),
        ]
    )

    assert verdict.status == "fail"
    assert verdict.actionable_failures == ["Functional Test (Polling)"]
    assert verdict.pending == ["Visual Regression Test"]
