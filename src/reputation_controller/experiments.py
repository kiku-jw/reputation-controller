"""Dry-run experiment plans for proof-sprint improvements."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable


@dataclass(frozen=True)
class StructuralProbeSpec:
    name: str
    language: str
    pattern: str


@dataclass(frozen=True)
class ContextPackPlan:
    tool: str
    output_path: Path
    command: list[str]

    def to_dict(self) -> dict:
        return {
            "tool": self.tool,
            "output_path": str(self.output_path),
            "command": self.command,
        }


@dataclass(frozen=True)
class StructuralProbePlan:
    tool: str
    name: str
    output_path: Path
    command: list[str]

    def to_dict(self) -> dict:
        return {
            "tool": self.tool,
            "name": self.name,
            "output_path": str(self.output_path),
            "command": self.command,
        }


@dataclass(frozen=True)
class ContextProbeExperimentPlan:
    sprint_id: str
    repo_path: Path
    packet_path: Path
    evidence_dir: Path
    context_pack: ContextPackPlan
    structural_probes: list[StructuralProbePlan] = field(default_factory=list)
    success_condition: str = (
        "The variant either kills faster with a better reason or produces a "
        "cleaner PR packet with less manual context gathering."
    )
    kill_condition: str = (
        "If the added tools increase setup/context time without improving proof "
        "or PR quality, remove them."
    )

    def to_dict(self) -> dict:
        return {
            "sprint_id": self.sprint_id,
            "repo_path": str(self.repo_path),
            "public_actions_allowed": False,
            "baseline": {
                "packet_path": str(self.packet_path),
                "evidence_dir": str(self.evidence_dir / "baseline"),
                "description": "Current packet flow without additional context probes.",
            },
            "variant": {
                "description": (
                    "Current packet flow plus context pack and structural probe evidence."
                ),
                "context_pack": self.context_pack.to_dict(),
                "structural_probes": [
                    probe.to_dict() for probe in self.structural_probes
                ],
            },
            "success_condition": self.success_condition,
            "kill_condition": self.kill_condition,
        }


def build_context_probe_experiment(
    *,
    sprint_id: str,
    repo_path: Path,
    packet_path: Path,
    evidence_dir: Path,
    include_paths: Iterable[str] = (),
    ast_grep_patterns: Iterable[StructuralProbeSpec] = (),
    semgrep_configs: Iterable[str] = (),
) -> ContextProbeExperimentPlan:
    include_list = [item for item in include_paths if item]
    variant_dir = evidence_dir / "variant"
    context_pack_path = variant_dir / "context-pack.xml"
    context_command = [
        "npx",
        "--yes",
        "repomix",
        str(repo_path),
        "--output",
        str(context_pack_path),
    ]
    if include_list:
        context_command.extend(["--include", ",".join(include_list)])

    probe_dir = variant_dir / "structural-probes"
    structural_probes = [
        _ast_grep_probe(repo_path, probe_dir, spec) for spec in ast_grep_patterns
    ]
    structural_probes.extend(
        _semgrep_probe(repo_path, probe_dir, config) for config in semgrep_configs
    )

    return ContextProbeExperimentPlan(
        sprint_id=sprint_id,
        repo_path=repo_path,
        packet_path=packet_path,
        evidence_dir=evidence_dir,
        context_pack=ContextPackPlan(
            tool="repomix",
            output_path=context_pack_path,
            command=context_command,
        ),
        structural_probes=structural_probes,
    )


def _ast_grep_probe(
    repo_path: Path,
    probe_dir: Path,
    spec: StructuralProbeSpec,
) -> StructuralProbePlan:
    safe_name = _slug(spec.name)
    return StructuralProbePlan(
        tool="ast-grep",
        name=safe_name,
        output_path=probe_dir / f"ast-grep-{safe_name}.json",
        command=[
            "npx",
            "--yes",
            "@ast-grep/cli",
            "scan",
            "--pattern",
            spec.pattern,
            "--lang",
            spec.language,
            str(repo_path),
            "--json",
        ],
    )


def _semgrep_probe(
    repo_path: Path,
    probe_dir: Path,
    config: str,
) -> StructuralProbePlan:
    safe_name = _slug(config)
    return StructuralProbePlan(
        tool="semgrep",
        name=safe_name,
        output_path=probe_dir / f"semgrep-{safe_name}.json",
        command=[
            "semgrep",
            "scan",
            "--config",
            config,
            "--json",
            str(repo_path),
        ],
    )


def _slug(value: str) -> str:
    slug = re.sub(r"[^A-Za-z0-9]+", "-", value.strip()).strip("-").lower()
    return slug or "probe"
