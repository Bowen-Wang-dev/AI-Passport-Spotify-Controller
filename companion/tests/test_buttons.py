from dataclasses import replace

import pytest

from passport_companion.buttons import ButtonController
from passport_companion.mock import MockSpotifyAdapter
from passport_companion.models import PlaybackSnapshot, PlaybackStatus


class Clock:
    def __init__(self) -> None:
        self.now = 100.0

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


@pytest.fixture
def setup():
    adapter = MockSpotifyAdapter()
    clock = Clock()
    return adapter, clock, ButtonController(adapter, clock=clock)


def test_ok_pause_play_and_down(setup):
    adapter, clock, controller = setup
    assert controller.press("ok").ok
    assert adapter.state.status == PlaybackStatus.PAUSED
    clock.advance(0.1)
    assert controller.press("ok").ok
    assert adapter.state.status == PlaybackStatus.PLAYING
    assert controller.press("down").ok
    assert [call[0] for call in adapter.calls] == ["pause", "play", "next"]


def test_first_up_seeks_zero(setup):
    adapter, _, controller = setup
    assert controller.press("up").ok
    assert adapter.calls == [("seek_zero", 0)]
    assert adapter.state.position_ms == 0


@pytest.mark.parametrize("elapsed,action", [(0.04, "previous"), (1.999, "previous"),
                                           (2.0, "previous"), (2.000001, "seek_zero")])
def test_up_window_boundaries(setup, elapsed, action):
    adapter, clock, controller = setup
    controller.press("up")
    clock.advance(elapsed)
    assert controller.press("up").action == action
    assert adapter.calls[-1][0] == action


def test_previous_disarms_even_on_failure(setup):
    adapter, clock, controller = setup
    controller.press("up")
    adapter.fail.add("previous")
    clock.advance(0.1)
    assert not controller.press("up").ok
    clock.advance(0.1)
    assert controller.press("up").action == "seek_zero"


def test_debounce_is_not_double_click(setup):
    adapter, clock, controller = setup
    controller.press("up")
    clock.advance(0.039)
    assert controller.press("up").error == "debounced"
    assert len(adapter.calls) == 1
    clock.advance(0.1)
    assert controller.press("up").action == "previous"


def test_failed_seek_does_not_arm(setup):
    adapter, clock, controller = setup
    adapter.fail.add("seek_zero")
    assert not controller.press("up").ok
    clock.advance(0.1)
    assert not controller.press("up").ok
    assert adapter.calls == [("seek_zero", 0), ("seek_zero", 0)]


def test_track_change_and_change_back_clears(setup):
    adapter, clock, controller = setup
    original = adapter.state
    controller.press("up")
    adapter.state = replace(original, track=replace(original.track, title="Other fiction"), track_revision=2)
    controller.observe(adapter.state)
    adapter.state = replace(original, track_revision=3)
    clock.advance(0.1)
    assert controller.press("up").action == "seek_zero"


def test_unobserved_same_title_new_revision_clears(setup):
    adapter, clock, controller = setup
    controller.press("up")
    adapter.state = replace(adapter.state, track_revision=adapter.state.track_revision + 2)
    clock.advance(0.1)
    assert controller.press("up").action == "seek_zero"


def test_connection_reset_even_same_track(setup):
    adapter, clock, controller = setup
    controller.press("up")
    adapter.state = replace(adapter.state, connection_id=2)
    clock.advance(0.1)
    assert controller.press("up").action == "seek_zero"


def test_explicit_reset(setup):
    _, clock, controller = setup
    controller.press("up")
    controller.reset()
    clock.advance(0.1)
    assert controller.press("up").action == "seek_zero"


def test_paused_seek_never_plays(setup):
    adapter, _, controller = setup
    adapter.state = replace(adapter.state, status=PlaybackStatus.PAUSED)
    assert controller.press("up").ok
    assert adapter.state.status == PlaybackStatus.PAUSED
    assert adapter.calls == [("seek_zero", 0)]


def test_unavailable_and_reconnect(setup):
    adapter, clock, controller = setup
    original = adapter.state
    controller.press("up")
    adapter.state = PlaybackSnapshot(connection_id=2)
    assert controller.press("up").error == "not_connected"
    adapter.state = replace(original, connection_id=3)
    clock.advance(0.1)
    assert controller.press("up").action == "seek_zero"


def test_window_starts_after_success_not_dispatch(setup):
    adapter, clock, controller = setup
    seek = adapter.seek

    def slow_seek(position):
        clock.advance(1.5)
        return seek(position)

    adapter.seek = slow_seek
    assert controller.press("up").ok
    clock.advance(1.9)
    assert controller.press("up").action == "previous"


def test_change_during_seek_does_not_arm(setup):
    adapter, clock, controller = setup
    seek = adapter.seek

    def changed_seek(position):
        result = seek(position)
        adapter.state = replace(adapter.state, track_revision=100)
        return result

    adapter.seek = changed_seek
    assert controller.press("up").error == "state_changed"
    clock.advance(0.1)
    controller.press("up")
    assert all(c[0] == "seek_zero" for c in adapter.calls)


def test_exception_resets_and_invalid_button_is_rejected(setup):
    adapter, clock, controller = setup
    controller.press("up")
    snapshot = adapter.snapshot
    adapter.snapshot = lambda: (_ for _ in ()).throw(OSError("unavailable"))
    assert controller.press("up").error == "adapter_failed"
    adapter.snapshot = snapshot
    clock.advance(0.1)
    assert controller.press("up").action == "seek_zero"
    assert controller.press("volume").error == "invalid_button"


def test_unsupported_seek_and_ad(setup):
    adapter, _, controller = setup
    adapter.state = replace(adapter.state, capabilities=replace(adapter.state.capabilities, seek=False))
    assert controller.press("up").error == "not_supported"
    adapter.state = replace(adapter.state, status=PlaybackStatus.AD)
    assert controller.press("ok").error == "not_supported"
