from reputation_controller.state import ControllerState, Sprint, StateStore


def test_state_store_resolves_active_sprint(tmp_path):
    store = StateStore(tmp_path / "state.json")
    store.save(
        ControllerState(
            active_sprints=[
                Sprint(
                    sprint_id="fossasia-visdom-1431",
                    repo="fossasia/visdom",
                    issue_number=1431,
                    title="Unit tests fail",
                    status="packet_created",
                )
            ]
        )
    )

    resolved = store.resolve_sprint("fossasia-visdom-1431", "kill")
    state = store.load()

    assert resolved is True
    assert state.active_sprints == []
    assert state.completed_sprints[0].sprint_id == "fossasia-visdom-1431"
    assert state.completed_sprints[0].status == "kill"


def test_state_store_returns_false_for_missing_sprint(tmp_path):
    store = StateStore(tmp_path / "state.json")
    store.save(ControllerState())

    assert store.resolve_sprint("missing", "kill") is False
