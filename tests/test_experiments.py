import importlib
import json
import sys
from pathlib import Path

from reputation_controller.experiments import (
    StructuralProbeSpec,
    build_context_probe_experiment,
)


def test_context_probe_experiment_plan_is_dry_run_and_deterministic(tmp_path: Path):
    repo_path = tmp_path / "repo"
    repo_path.mkdir()
    packet_path = tmp_path / ".controller/tasks/demo.md"
    packet_path.parent.mkdir(parents=True)
    packet_path.write_text("Sprint packet")
    evidence_dir = tmp_path / ".controller/evidence/demo"

    plan = build_context_probe_experiment(
        sprint_id="demo",
        repo_path=repo_path,
        packet_path=packet_path,
        evidence_dir=evidence_dir,
        include_paths=["src", "tests"],
        ast_grep_patterns=[
            StructuralProbeSpec(
                name="broad-except",
                language="python",
                pattern="except Exception:",
            )
        ],
        semgrep_configs=["p/python"],
    ).to_dict()

    assert plan["sprint_id"] == "demo"
    assert plan["public_actions_allowed"] is False
    assert plan["baseline"] == {
        "packet_path": str(packet_path),
        "evidence_dir": str(evidence_dir / "baseline"),
        "description": "Current packet flow without additional context probes.",
    }
    assert plan["variant"]["description"] == (
        "Current packet flow plus context pack and structural probe evidence."
    )
    assert plan["variant"]["context_pack"] == {
        "tool": "repomix",
        "output_path": str(evidence_dir / "variant/context-pack.xml"),
        "command": [
            "npx",
            "--yes",
            "repomix",
            str(repo_path),
            "--output",
            str(evidence_dir / "variant/context-pack.xml"),
            "--include",
            "src,tests",
        ],
    }
    assert plan["variant"]["structural_probes"] == [
        {
            "tool": "ast-grep",
            "name": "broad-except",
            "output_path": str(
                evidence_dir / "variant/structural-probes/ast-grep-broad-except.json"
            ),
            "command": [
                "npx",
                "--yes",
                "@ast-grep/cli",
                "scan",
                "--pattern",
                "except Exception:",
                "--lang",
                "python",
                str(repo_path),
                "--json",
            ],
        },
        {
            "tool": "semgrep",
            "name": "p-python",
            "output_path": str(
                evidence_dir / "variant/structural-probes/semgrep-p-python.json"
            ),
            "command": [
                "semgrep",
                "scan",
                "--config",
                "p/python",
                "--json",
                str(repo_path),
            ],
        },
    ]
    assert "kills faster" in plan["success_condition"]
    assert "increase setup/context time" in plan["kill_condition"]


def test_experiment_plan_cli_prints_json_without_creating_state(
    tmp_path: Path,
    monkeypatch,
    capsys,
):
    cli = importlib.import_module("reputation_controller.__main__")
    config_path = tmp_path / "controller.json"
    config_path.write_text(
        json.dumps(
            {
                "workspace": str(tmp_path),
                "state_dir": ".controller/state",
                "dry_run": True,
                "repos": [],
            }
        )
    )
    repo_path = tmp_path / "repo"
    repo_path.mkdir()
    packet_path = tmp_path / ".controller/tasks/demo.md"
    packet_path.parent.mkdir(parents=True)
    packet_path.write_text("Sprint packet")

    monkeypatch.setattr(
        sys,
        "argv",
        [
            "reputation-controller",
            "--config",
            str(config_path),
            "experiment-plan",
            "--sprint-id",
            "demo",
            "--repo-path",
            str(repo_path),
            "--packet-path",
            str(packet_path),
            "--include",
            "src",
            "--ast-grep",
            "broad-except:python:except Exception:",
            "--semgrep-config",
            "p/python",
        ],
    )

    result = cli.main()

    assert result == 0
    output = json.loads(capsys.readouterr().out)
    assert output["sprint_id"] == "demo"
    assert output["variant"]["context_pack"]["tool"] == "repomix"
    assert output["variant"]["structural_probes"][0]["name"] == "broad-except"
    assert output["variant"]["structural_probes"][1]["name"] == "p-python"
    assert not (tmp_path / ".controller/state/state.json").exists()
