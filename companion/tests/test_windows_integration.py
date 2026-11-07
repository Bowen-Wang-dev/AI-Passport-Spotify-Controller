"""Opt-in actual Spotify tests. Never infer a real pass from Mock tests."""
import os
import sys
import time

import pytest

from passport_companion.buttons import ButtonController
from passport_companion.models import PlaybackStatus
from passport_companion.spotify import WindowsSpotifyAdapter

pytestmark = pytest.mark.integration


@pytest.fixture
def live():
    if os.environ.get("PASSPORT_RUN_INTEGRATION") != "1":
        pytest.skip("Set PASSPORT_RUN_INTEGRATION=1 for actual Windows Spotify")
    if sys.platform != "win32":
        pytest.skip("Actual integration requires Windows")
    adapter = WindowsSpotifyAdapter(startup_timeout=5, confirmation_timeout=3)
    try:
        assert adapter.snapshot().connected, "Open Spotify Desktop and select a normal track"
        yield adapter
    finally:
        adapter.close()


def test_actual_metadata_and_artwork(live):
    from passport_companion.artwork import ArtworkProcessor

    state = live.snapshot()
    assert state.track and state.track.title and state.track.artist and state.track.album
    assert state.track.duration_ms and 0 <= state.position_ms <= state.track.duration_ms
    assert state.status in {PlaybackStatus.PLAYING, PlaybackStatus.PAUSED}
    assert state.artwork, "Choose a track with cover art for this test"
    image = ArtworkProcessor(size=160).process(state.artwork)
    assert image.status == "ok" and image.jpeg


@pytest.mark.controls
def test_actual_transport_and_up_state_machine(live):
    if os.environ.get("PASSPORT_RUN_CONTROLS") != "1":
        pytest.skip("Set PASSPORT_RUN_CONTROLS=1; this changes actual playback")
    original = live.snapshot()
    assert original.track and original.track.duration_ms and original.track.duration_ms > 15_000
    assert original.capabilities.seek and original.capabilities.next and original.capabilities.previous
    controller = ButtonController(live)
    try:
        if original.status == PlaybackStatus.PLAYING:
            assert live.pause().ok
        assert live.seek(5_000).ok, "Must start away from zero to prove Seek(0) moves the timeline"
        assert live.snapshot().position_ms >= 4_500
        first = controller.press("up")
        assert first.ok and first.action == "seek_zero", first
        assert live.snapshot().position_ms <= 500
        assert live.snapshot().status == PlaybackStatus.PAUSED
        time.sleep(2.05)
        assert live.seek(6_000).ok
        expired = controller.press("up")
        assert expired.ok and expired.action == "seek_zero", expired
        down = controller.press("down")
        assert down.ok and down.action == "next", down
        assert live.snapshot().track.key != original.track.key
        if live.snapshot().status == PlaybackStatus.PLAYING:
            assert live.pause().ok
        assert live.seek(5_000).ok
        assert controller.press("up").ok
        time.sleep(0.1)
        second = controller.press("up")
        assert second.ok and second.action == "previous", second
        assert live.snapshot().track.key == original.track.key, "Next/Previous did not return to original track"
        current = live.snapshot()
        if current.status == PlaybackStatus.PLAYING:
            assert live.pause().ok
        assert controller.press("ok").ok
        assert live.snapshot().status == PlaybackStatus.PLAYING
        assert live.seek(5_000).ok
        assert live.seek(0).ok
        assert live.snapshot().status == PlaybackStatus.PLAYING
        assert live.snapshot().position_ms <= 800
        assert controller.press("ok").ok
        assert live.snapshot().status == PlaybackStatus.PAUSED
    finally:
        # Only restore a position to the exact original track, never to a new one.
        state = live.snapshot()
        if state.track and state.track.key == original.track.key:
            restored = live.seek(original.position_ms)
            assert restored.ok, f"Could not restore original position: {restored}"
        if original.status == PlaybackStatus.PLAYING and live.snapshot().status != PlaybackStatus.PLAYING:
            assert live.play().ok
        elif original.status == PlaybackStatus.PAUSED and live.snapshot().status == PlaybackStatus.PLAYING:
            assert live.pause().ok
