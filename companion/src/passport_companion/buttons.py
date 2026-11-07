"""Three logical buttons; UP is never a generic previous-track media key."""
from __future__ import annotations

import logging
import time
from collections.abc import Callable

from .models import ControlResult, PlaybackSnapshot, PlaybackStatus, SpotifyAdapter

log = logging.getLogger(__name__)


class ButtonController:
    def __init__(self, adapter: SpotifyAdapter, *, clock: Callable[[], float] = time.monotonic,
                 window_seconds: float = 2.0, debounce_seconds: float = 0.04) -> None:
        if window_seconds <= 0 or not 0 <= debounce_seconds < window_seconds:
            raise ValueError("Invalid button timing")
        self._adapter, self._clock = adapter, clock
        self._window, self._debounce = window_seconds, debounce_seconds
        self._armed: tuple[object, ...] | None = None
        self._armed_at = 0.0
        self._identity: tuple[object, ...] | None = None
        self._last_press: dict[str, float] = {}

    def reset(self) -> None:
        self._armed = None
        self._armed_at = 0.0
        self._identity = None
        self._last_press.clear()

    def observe(self, snapshot: PlaybackSnapshot) -> None:
        now = self._clock()
        if snapshot.identity != self._identity or not snapshot.connected:
            self._armed = None
            self._last_press.clear()
        if self._armed is not None and not 0 <= now - self._armed_at <= self._window:
            self._armed = None
        self._identity = snapshot.identity

    def press(self, button: str) -> ControlResult:
        if button not in {"up", "ok", "down"}:
            return ControlResult(button, False, "invalid_button")
        try:
            snapshot = self._adapter.snapshot()
            self.observe(snapshot)
            if not snapshot.connected or snapshot.track is None:
                self.reset()
                return ControlResult(button, False, "not_connected")
            now = self._clock()
            last = self._last_press.get(button)
            if last is not None and 0 <= now - last < self._debounce:
                return ControlResult(button, False, "debounced")
            self._last_press[button] = now
            if button == "ok":
                if snapshot.status == PlaybackStatus.PLAYING:
                    return self._adapter.pause()
                if snapshot.status in {PlaybackStatus.PAUSED, PlaybackStatus.STOPPED}:
                    return self._adapter.play()
                return ControlResult("play_pause", False, "not_supported")
            if button == "down":
                self._armed = None
                return self._adapter.next()
            if self._armed == snapshot.identity and 0 <= now - self._armed_at <= self._window:
                self._armed = None
                return self._adapter.previous()
            self._armed = None
            result = self._adapter.seek(0)
            # A successful dispatch alone is not enough. The adapter confirms the
            # seek and we reject a concurrent track/connection change before arming.
            after = self._adapter.snapshot()
            self.observe(after)
            if result.ok and after.identity == snapshot.identity:
                self._armed = after.identity
                self._armed_at = self._clock()
            elif result.ok:
                return ControlResult("seek_zero", False, "state_changed")
            return result
        except Exception as exc:
            self.reset()
            log.warning("Button operation failed (%s)", type(exc).__name__)
            return ControlResult(button, False, "adapter_failed", type(exc).__name__)
