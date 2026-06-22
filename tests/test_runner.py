from pathlib import Path

from reputation_controller.runner import WorkerSpec, build_worker_command


def test_worker_command_is_packet_bound_and_does_not_include_secrets():
    command = build_worker_command(
        WorkerSpec(
            repo_path=Path("/work/visdom"),
            packet_path=Path("/work/.controller/tasks/fossasia-visdom-1197.md"),
            evidence_dir=Path("/work/.controller/evidence/fossasia-visdom-1197"),
            result_path=Path(
                "/work/.controller/evidence/fossasia-visdom-1197/worker-result.json"
            ),
            model="codex/gpt-5.5",
        )
    )

    joined = " ".join(command)
    assert command[:2] == ["codex", "exec"]
    assert "--cd" in command
    assert "--add-dir" in command
    assert "--full-auto" in command
    assert 'service_tier="fast"' in command
    assert "gpt-5.5" in command
    assert "codex/gpt-5.5" not in command
    assert "--dangerously-bypass-approvals-and-sandbox" not in command
    assert "/work/visdom" in command
    assert "fossasia-visdom-1197.md" in joined
    assert "worker-result.json" in joined
    assert "GITHUB_TOKEN" not in joined
    assert "LLM_API_KEY" not in joined
