from dataclasses import dataclass, replace
from threading import Event
import time

from passport_companion.mock import MockSpotifyAdapter
from passport_companion.service import Companion


@dataclass(frozen=True)
class Pair:
    current: str = ""
    next: str = ""
    current_at_ms: int | None = None


@dataclass(frozen=True)
class Result:
    status: str = "synced"
    detail: str = ""
    label: str = "Fictional line"

    def at(self, position_ms):
        return Pair(f"{self.label}@{position_ms}", "Original next line", position_ms)


class BlockingLyrics:
    def __init__(self):
        self.started = Event()
        self.release = Event()
        self.calls = []

    def lookup(self, track):
        self.calls.append(track.key)
        self.started.set()
        assert self.release.wait(3), "Test must release worker"
        return Result(label=track.title)


def poll_until(service, predicate):
    end = time.monotonic() + 3
    while time.monotonic() < end:
        value = service.poll()
        if predicate(value):
            return value
        time.sleep(0.005)
    raise AssertionError("Background result was not observed")


def test_lyrics_cannot_block_controls_and_old_track_results_are_discarded():
    adapter, lyrics = MockSpotifyAdapter(), BlockingLyrics()
    service = Companion(adapter, lyrics=lyrics)
    try:
        first = service.poll()
        assert first["lyrics"]["status"] == "pending"
        assert lyrics.started.wait(1)
        assert service.press("down").ok
        second = service.poll()
        assert second["lyrics"]["current"] == ""
        assert second["title"] != first["title"]
        lyrics.release.set()
        result = poll_until(service, lambda v: v["lyrics"]["status"] == "synced")
        assert result["lyrics"]["current"].startswith(result["title"])
        assert len(lyrics.calls) == 2
    finally:
        lyrics.release.set()
        service.close()


def test_seek_pause_resume_and_host_drag_reselect_from_latest_position():
    adapter, lyrics = MockSpotifyAdapter(), BlockingLyrics()
    lyrics.release.set()
    service = Companion(adapter, lyrics=lyrics)
    try:
        poll_until(service, lambda v: v["lyrics"]["status"] == "synced")
        assert service.press("ok").ok
        adapter.state = replace(adapter.state, position_ms=80_000)
        paused = service.poll()
        assert paused["status"] == "paused"
        assert paused["lyrics"]["current"].endswith("@80000")
        assert service.poll()["position_ms"] == 80_000
        assert service.press("up").ok
        assert service.poll()["lyrics"]["current"].endswith("@0")
        assert len(lyrics.calls) == 1
    finally:
        service.close()


def test_disconnect_clears_lyrics_and_artwork():
    adapter, lyrics = MockSpotifyAdapter(), BlockingLyrics()
    lyrics.release.set()
    service = Companion(adapter, lyrics=lyrics)
    try:
        poll_until(service, lambda v: v["lyrics"]["status"] == "synced")
        adapter.close()
        view = service.poll()
        assert not view["connected"]
        assert view["lyrics"]["current"] == ""
        assert view["artwork"]["status"] == "missing"
    finally:
        service.close()


def test_cover_conversion_only_when_bytes_change():
    class Art:
        calls = 0

        def process(self, _data):
            self.calls += 1
            return type("Output", (), {"status": "missing", "jpeg": None})()

    art = Art()
    service = Companion(MockSpotifyAdapter(), artwork=art)
    try:
        service.poll()
        service.poll()
        assert art.calls == 1
    finally:
        service.close()
