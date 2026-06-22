from pathlib import Path

from reputation_controller.state import ControllerState, Sprint, StateStore


def test_state_store_round_trips_active_sprints(tmp_path: Path):
    path = tmp_path / "state.json"
    store = StateStore(path)
    state = ControllerState(
        active_sprints=[
            Sprint(
                sprint_id="fossasia-visdom-1197",
                repo="fossasia/visdom",
                issue_number=1197,
                title="Cypress E2E still failing",
                status="packet_created",
            )
        ],
        open_hypotheses=["polling env clear race"],
        target_history=["fossasia/visdom"],
    )

    store.save(state)
    loaded = store.load()

    assert loaded.active_sprints[0].repo == "fossasia/visdom"
    assert loaded.open_hypotheses == ["polling env clear race"]
    assert loaded.target_history == ["fossasia/visdom"]
