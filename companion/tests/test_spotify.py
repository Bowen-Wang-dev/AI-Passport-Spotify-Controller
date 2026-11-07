from dataclasses import dataclass, replace
from typing import Callable

import pytest

from passport_companion.models import PlaybackStatus
from passport_companion.spotify import MAX_ARTWORK_BYTES, SpotifyUnavailable, WindowsSpotifyAdapter


@dataclass
class RawState:
    title: str = "Synthetic song"
    artist: str = "Invented artist"
    album: str = "Test album"
    status: int = 3
    position_ms: int = 20_000
    duration_ms: int = 180_000
    album_art: bytes = b""
    can_seek: bool = True
    can_skip_next: bool = True
    can_skip_prev: bool = True
    is_ad: bool = False


class Clock:
    now = 0.0

    def __call__(self):
        return self.now

    def sleep(self, seconds):
        self.now += seconds


class Native:
    def __init__(self):
        self.raw = RawState()
        self.calls = []
        self.accepted = True
        self.effective = True
        self.raises = False
        self.read_raises = False
        self.callbacks: dict[str, Callable] = {}

    def start(self):
        pass

    def close(self):
        self.calls.append("close")

    def on_closed(self, cb):
        self.callbacks["closed"] = cb
        return 1

    def on_opened(self, cb):
        self.callbacks["opened"] = cb
        return 2

    def on_track_changed(self, cb):
        self.callbacks["track"] = cb
        return 3

    def latest_state(self):
        if self.read_raises:
            raise OSError("read failed")
        return self.raw

    @property
    def position_smooth_ms(self):
        return self.raw.position_ms

    def execute(self, name, **changes):
        self.calls.append(name)
        if self.raises:
            raise OSError("transport failed")
        if self.accepted and self.effective:
            self.raw = replace(self.raw, **changes)
        return self.accepted

    def play(self):
        return self.execute("play", status=3)

    def pause(self):
        return self.execute("pause", status=2)

    def next(self):
        return self.execute("next", title="Next synthetic song")

    def previous(self):
        return self.execute("previous", title="Previous synthetic song")

    def seek_ms(self, position):
        return self.execute(("seek_ms", position), position_ms=position)


@pytest.fixture
def setup():
    native, clock = Native(), Clock()
    adapter = WindowsSpotifyAdapter(native, clock=clock, sleep=clock.sleep,
                                    startup_timeout=0, confirmation_timeout=0.2)
    return native, clock, adapter


def test_maps_verified_binding_fields_and_caps(setup):
    native, _, adapter = setup
    state = adapter.snapshot()
    assert state.track.title == native.raw.title
    assert state.track.artist == native.raw.artist
    assert state.track.album == native.raw.album
    assert state.track.duration_ms == 180_000
    assert state.position_ms == 20_000
    assert state.status == PlaybackStatus.PLAYING
    assert state.capabilities.seek and state.capabilities.next
    assert state.capabilities.pause and not state.capabilities.play


def test_play_pause_next_previous_are_observed(setup):
    native, _, adapter = setup
    assert adapter.pause().ok
    assert adapter.play().ok
    assert adapter.next().ok
    assert adapter.previous().ok
    assert native.calls == ["pause", "play", "next", "previous"]


def test_seek_zero_is_observed_and_preserves_pause(setup):
    native, _, adapter = setup
    native.raw.status = 2
    assert adapter.seek(0).ok
    assert native.raw.position_ms == 0 and native.raw.status == 2
    assert native.calls == [("seek_ms", 0)]


def test_dispatch_true_is_not_seek_success(setup):
    native, _, adapter = setup
    native.effective = False
    assert adapter.seek(0).error == "confirmation_timeout"
    assert adapter.pause().error == "confirmation_timeout"
    assert adapter.next().error == "confirmation_timeout"


def test_track_callback_or_duration_change_alone_cannot_confirm_skip(setup):
    native, _, adapter = setup

    def only_callback():
        native.callbacks["track"](None, None)
        native.raw.duration_ms += 100
        return True

    native.next = only_callback
    assert adapter.next().error == "confirmation_timeout"


def test_transient_metadata_cannot_confirm_skip(setup):
    native, clock, adapter = setup
    original = native.raw
    sleep = clock.sleep

    def transient_next():
        native.raw = replace(original, title="Transient candidate")
        return True

    def updated_sleep(seconds):
        sleep(seconds)
        native.raw = original

    native.next = transient_next
    adapter._sleep = updated_sleep
    assert adapter.next().error == "confirmation_timeout"


def test_native_false_and_exception(setup):
    native, _, adapter = setup
    native.accepted = False
    assert adapter.seek(0).error == "command_rejected"
    native.raises = True
    assert adapter.next().error == "call_failed"


def test_missing_track_cannot_control(setup):
    native, _, adapter = setup
    native.raw.title = ""
    assert not adapter.snapshot().connected
    assert adapter.play().error == "not_connected"
    assert not native.calls


def test_ad_and_capability_unavailable(setup):
    native, _, adapter = setup
    native.raw.is_ad = True
    assert adapter.snapshot().status == PlaybackStatus.AD
    assert adapter.seek(0).error == "not_supported"
    assert adapter.next().error == "not_supported"
    native.raw.is_ad = False
    native.raw.can_seek = False
    assert adapter.seek(0).error == "not_supported"


@pytest.mark.parametrize("value", [-1, 999_999, True, 1.5])
def test_invalid_seek_never_dispatches(setup, value):
    native, _, adapter = setup
    assert adapter.seek(value).error == "invalid_position"
    assert not native.calls


def test_clamps_position_unknown_duration_and_art_limit(setup):
    native, _, adapter = setup
    native.raw.position_ms = 999_999
    assert adapter.snapshot().position_ms == 180_000
    native.raw.duration_ms = 0
    assert adapter.snapshot().track.duration_ms is None
    native.raw.position_ms = -10
    native.raw.album_art = b"x" * (MAX_ARTWORK_BYTES + 1)
    s = adapter.snapshot()
    assert s.position_ms == 0 and not s.artwork


def test_native_connection_and_track_callbacks_change_identity(setup):
    native, _, adapter = setup
    initial = adapter.snapshot()
    native.callbacks["track"](None, None)
    assert adapter.snapshot().identity != initial.identity
    native.callbacks["closed"]()
    assert not adapter.snapshot().connected
    native.callbacks["opened"]()
    assert adapter.snapshot().connection_id != initial.connection_id


def test_failure_read_and_idempotent_close(setup):
    native, _, adapter = setup
    initial = adapter.snapshot()
    native.read_raises = True
    assert adapter.snapshot().error == "state_read_failed"
    native.read_raises = False
    assert adapter.snapshot().connected
    assert adapter.snapshot().connection_id != initial.connection_id
    adapter.close()
    adapter.close()
    assert native.calls.count("close") == 1
    assert not adapter.snapshot().connected


def test_paused_seek_unexpected_resume_is_failure_and_restored(setup):
    native, _, adapter = setup
    native.raw.status = 2
    native.seek_ms = lambda position: native.execute(("seek_ms", position), position_ms=0, status=3)
    result = adapter.seek(0)
    assert result.error == "pause_not_preserved"
    assert native.raw.status == 2
    assert "play" not in native.calls


def test_start_failure_cleans_up(setup):
    native, clock, _ = setup
    native.start = lambda: (_ for _ in ()).throw(OSError())
    with pytest.raises(SpotifyUnavailable):
        WindowsSpotifyAdapter(native, clock=clock, sleep=clock.sleep, startup_timeout=0)
    assert "close" in native.calls
