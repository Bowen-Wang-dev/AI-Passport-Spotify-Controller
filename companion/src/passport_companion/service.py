"""Local view orchestration; slow lyric I/O never runs on the button path."""
from __future__ import annotations

import logging
import time
from collections.abc import Callable
from concurrent.futures import Future, ThreadPoolExecutor, TimeoutError
from typing import Any

from .artwork import ArtworkProcessor, ArtworkResult
from .buttons import ButtonController
from .lyrics import LyricsAdapter, LyricsResult
from .models import ControlResult, SpotifyAdapter, Track

log = logging.getLogger(__name__)


class Companion:
    def __init__(self, spotify: SpotifyAdapter, *, lyrics: LyricsAdapter | None = None,
                 artwork: ArtworkProcessor | None = None,
                 clock: Callable[[], float] = time.monotonic) -> None:
        self.spotify = spotify
        self.buttons = ButtonController(spotify, clock=clock)
        self._clock = clock
        self._lyrics_adapter = lyrics
        self._artwork_processor = artwork or ArtworkProcessor()
        self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="lrclib") if lyrics else None
        self._future: Future[LyricsResult] | None = None
        self._future_key: tuple[object, ...] | None = None
        self._track_key: tuple[object, ...] | None = None
        self._lyrics: LyricsResult | None = None
        self._retry_at = 0.0
        self._art_input: bytes | None = None
        self._art: ArtworkResult | None = None

    def press(self, button: str) -> ControlResult:
        return self.buttons.press(button)

    def _lyrics_tick(self, track: Track | None, identity: tuple[object, ...] | None) -> None:
        if identity != self._track_key:
            self._lyrics = None
            self._retry_at = 0.0
            self._track_key = identity
        if self._future is not None and self._future.done():
            if self._future_key == identity:
                try:
                    self._lyrics = self._future.result()
                except Exception as exc:
                    log.warning("Lyrics lookup failed (%s)", type(exc).__name__)
                self._retry_at = self._clock() + 30.0
            self._future = None
        retry = self._lyrics is None or self._lyrics.status != "synced"
        if (self._executor and track is not None and identity is not None
                and self._future is None and retry and self._clock() >= self._retry_at):
            assert self._lyrics_adapter is not None
            self._future_key = identity
            self._future = self._executor.submit(self._lyrics_adapter.lookup, track)

    def poll(self) -> dict[str, Any]:
        state = self.spotify.snapshot()
        self.buttons.observe(state)
        self._lyrics_tick(state.track, state.identity)
        if self._art is None or self._art_input != state.artwork:
            self._art_input = state.artwork
            self._art = self._artwork_processor.process(state.artwork)
        pair = self._lyrics.at(state.position_ms) if self._lyrics else None
        return {
            "connected": state.connected,
            "status": state.status.value,
            "title": state.track.title if state.track else "",
            "artist": state.track.artist if state.track else "",
            "album": state.track.album if state.track else "",
            "position_ms": state.position_ms,
            "duration_ms": state.track.duration_ms if state.track else None,
            "connection_id": state.connection_id,
            "track_revision": state.track_revision,
            "capabilities": vars(state.capabilities),
            "artwork": {"status": self._art.status, "jpeg_bytes": len(self._art.jpeg or b"")},
            "lyrics": {
                "status": self._lyrics.status if self._lyrics else (
                    "pending" if self._lyrics_adapter and state.track else "disabled"),
                "current": pair.current if pair else "",
                "next": pair.next if pair else "",
                "current_at_ms": pair.current_at_ms if pair else None,
                "detail": self._lyrics.detail if self._lyrics else "",
            },
            "error": state.error,
        }

    def wait_for_lyrics(self, timeout: float = 5.0) -> None:
        if self._future is not None:
            try:
                self._future.result(timeout=timeout)
            except TimeoutError:
                pass
            except Exception as exc:
                log.warning("Lyrics worker failed (%s)", type(exc).__name__)

    def close(self) -> None:
        self.buttons.reset()
        if self._executor:
            self._executor.shutdown(wait=False, cancel_futures=True)
        self.spotify.close()
