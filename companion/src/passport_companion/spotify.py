"""libspotifyctl 0.3.4 boundary, with observed (not just dispatched) results."""
from __future__ import annotations

import logging
import sys
import threading
import time
from collections.abc import Callable
from typing import Any, Protocol

from .models import Capabilities, ControlResult, PlaybackSnapshot, PlaybackStatus, Track

log = logging.getLogger(__name__)
MAX_ARTWORK_BYTES = 4 * 1024 * 1024


class NativeClient(Protocol):
    def start(self) -> None: ...
    def close(self) -> None: ...
    def latest_state(self) -> Any: ...
    @property
    def position_smooth_ms(self) -> int: ...
    def play(self) -> bool: ...
    def pause(self) -> bool: ...
    def next(self) -> bool: ...
    def previous(self) -> bool: ...
    def seek_ms(self, position_ms: int) -> bool: ...
    def on_closed(self, callback: Callable[[], None]) -> int: ...
    def on_opened(self, callback: Callable[[], None]) -> int: ...
    def on_track_changed(self, callback: Callable[..., None]) -> int: ...


class SpotifyUnavailable(RuntimeError):
    pass


def _create_client() -> NativeClient:
    if sys.platform != "win32":
        raise SpotifyUnavailable("Windows x64 and Spotify Desktop are required")
    try:
        from libspotifyctl import SpotifyClient
        return SpotifyClient()
    except (ImportError, OSError, MemoryError) as exc:
        raise SpotifyUnavailable(f"libspotifyctl could not load: {type(exc).__name__}") from exc


class WindowsSpotifyAdapter:
    def __init__(
        self,
        client: NativeClient | None = None,
        *,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
        startup_timeout: float = 3.0,
        confirmation_timeout: float = 2.0,
    ) -> None:
        if startup_timeout < 0 or confirmation_timeout <= 0:
            raise ValueError("Invalid timeout")
        self._clock, self._sleep = clock, sleep
        self._timeout = confirmation_timeout
        self._client = client if client is not None else _create_client()
        self._lock = threading.RLock()
        self._connection_id = 1
        self._track_revision = 0
        self._key: tuple[object, ...] | None = None
        self._closed = False
        self._native_disconnected = False
        try:
            self._client.on_closed(self._on_closed)
            self._client.on_opened(self._on_opened)
            self._client.on_track_changed(self._on_track_changed)
            self._client.start()
            end = self._clock() + startup_timeout
            stable_key: tuple[object, ...] | None = None
            stable_since = self._clock()
            while self._clock() < end:
                state = self.snapshot()
                key = state.track.key if state.track else None
                if key != stable_key:
                    stable_key, stable_since = key, self._clock()
                if state.connected and key is not None and self._clock() - stable_since >= 0.15:
                    break
                self._sleep(min(0.05, max(0, end - self._clock())))
        except Exception as exc:
            self._client.close()
            raise SpotifyUnavailable(f"Spotify initialization failed: {type(exc).__name__}") from exc

    def _on_closed(self) -> None:
        with self._lock:
            self._connection_id += 1
            self._key = None
            self._native_disconnected = True

    def _on_opened(self) -> None:
        with self._lock:
            self._connection_id += 1
            self._native_disconnected = False

    def _on_track_changed(self, *_states: object) -> None:
        with self._lock:
            self._track_revision += 1

    def snapshot(self) -> PlaybackSnapshot:
        with self._lock:
            if self._closed or self._native_disconnected:
                return PlaybackSnapshot(connection_id=self._connection_id, error="not_connected")
        try:
            raw = self._client.latest_state()
            if not raw.title:
                with self._lock:
                    if self._key is not None:
                        self._connection_id += 1
                    self._key = None
                return PlaybackSnapshot(connection_id=self._connection_id, error="no_spotify_track")
            status = {1: PlaybackStatus.STOPPED, 2: PlaybackStatus.PAUSED,
                      3: PlaybackStatus.PLAYING, 4: PlaybackStatus.CHANGING}.get(
                          int(raw.status), PlaybackStatus.STOPPED)
            if raw.is_ad:
                status = PlaybackStatus.AD
            duration = int(raw.duration_ms) if raw.duration_ms > 0 else None
            track = Track(raw.title, raw.artist, raw.album, duration)
            position = max(0, int(self._client.position_smooth_ms))
            if duration is not None:
                position = min(position, duration)
            operable = status not in {PlaybackStatus.AD, PlaybackStatus.CHANGING}
            caps = Capabilities(
                seek=bool(raw.can_seek) and operable,
                next=bool(raw.can_skip_next) and operable,
                previous=bool(raw.can_skip_prev) and operable,
                # This binding exposes no can_play/can_pause. These are candidates;
                # the observed state transition still has to confirm each call.
                play=status in {PlaybackStatus.PAUSED, PlaybackStatus.STOPPED},
                pause=status == PlaybackStatus.PLAYING,
            )
            art = raw.album_art
            if len(art) > MAX_ARTWORK_BYTES:
                art = b""
                log.warning("Native artwork exceeds input limit; discarded")
            with self._lock:
                if track.key != self._key:
                    self._track_revision += 1
                    self._key = track.key
                return PlaybackSnapshot(track, status, position, caps, art,
                                        self._connection_id, self._track_revision)
        except Exception as exc:
            with self._lock:
                self._connection_id += 1
                self._key = None
            log.warning("Spotify state read failed (%s)", type(exc).__name__)
            return PlaybackSnapshot(connection_id=self._connection_id, error="state_read_failed")

    def _execute(
        self,
        action: str,
        capability: str,
        invoke: Callable[[], bool],
        confirm: Callable[[PlaybackSnapshot, PlaybackSnapshot, float], bool],
    ) -> ControlResult:
        before = self.snapshot()
        if not before.connected:
            return ControlResult(action, False, "not_connected")
        if not getattr(before.capabilities, capability):
            return ControlResult(action, False, "not_supported")
        try:
            if not invoke():
                return ControlResult(action, False, "command_rejected")
            start = self._clock()
            stable_since: float | None = None
            stable_key: tuple[object, ...] | None = None
            while True:
                after = self.snapshot()
                elapsed = self._clock() - start
                if not after.connected or after.connection_id != before.connection_id:
                    return ControlResult(action, False, "connection_reset")
                observation = (after.track.key if after.track else None, after.status)
                if confirm(before, after, elapsed):
                    if stable_since is None or observation != stable_key:
                        stable_since, stable_key = elapsed, observation
                    # Native track callbacks can precede complete metadata. Do not
                    # mistake a revision bump or a transient snapshot for success.
                    if elapsed - stable_since >= min(0.15, self._timeout / 2):
                        return ControlResult(action, True, detail="Observed in stable local Spotify state")
                else:
                    stable_since, stable_key = None, None
                if elapsed >= self._timeout:
                    return ControlResult(action, False, "confirmation_timeout",
                                         "Command dispatched, effect not observed")
                self._sleep(min(0.05, self._timeout - elapsed))
        except Exception as exc:
            log.warning("Spotify %s failed (%s)", action, type(exc).__name__)
            return ControlResult(action, False, "call_failed", type(exc).__name__)

    def play(self) -> ControlResult:
        return self._execute("play", "play", self._client.play,
                             lambda _b, a, _t: a.status == PlaybackStatus.PLAYING)

    def pause(self) -> ControlResult:
        return self._execute("pause", "pause", self._client.pause,
                             lambda _b, a, _t: a.status == PlaybackStatus.PAUSED)

    @staticmethod
    def _track_changed(before: PlaybackSnapshot, after: PlaybackSnapshot, _elapsed: float) -> bool:
        if before.track is None or after.track is None or after.status == PlaybackStatus.CHANGING:
            return False
        return (before.track.title, before.track.artist, before.track.album) != (
            after.track.title, after.track.artist, after.track.album)

    def next(self) -> ControlResult:
        return self._execute("next", "next", self._client.next, self._track_changed)

    def previous(self) -> ControlResult:
        return self._execute("previous", "previous", self._client.previous, self._track_changed)

    def seek(self, position_ms: int) -> ControlResult:
        if isinstance(position_ms, bool) or not isinstance(position_ms, int) or position_ms < 0:
            return ControlResult("seek_zero" if position_ms == 0 else "seek", False, "invalid_position")
        initial = self.snapshot()
        if initial.track and initial.track.duration_ms is not None and position_ms > initial.track.duration_ms:
            return ControlResult("seek", False, "invalid_position")
        paused_changed = False

        def confirm(before: PlaybackSnapshot, after: PlaybackSnapshot, elapsed: float) -> bool:
            nonlocal paused_changed
            if before.identity != after.identity:
                return False
            if before.status == PlaybackStatus.PAUSED and after.status != PlaybackStatus.PAUSED:
                paused_changed = True
                return False
            if after.status != before.status:
                return False
            expected = position_ms + (int(elapsed * 1000) if after.status == PlaybackStatus.PLAYING else 0)
            return abs(after.position_ms - expected) <= 500

        result = self._execute("seek_zero" if position_ms == 0 else "seek", "seek",
                               lambda: self._client.seek_ms(position_ms), confirm)
        if paused_changed:
            restored = self.pause()
            return ControlResult(result.action, False, "pause_not_preserved",
                                 f"Unexpected resume; pause restoration success={restored.ok}")
        return result

    def close(self) -> None:
        with self._lock:
            if self._closed:
                return
            self._closed = True
            self._connection_id += 1
        self._client.close()
