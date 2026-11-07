"""Deterministic in-memory player; never controls Windows or produces audio."""
from __future__ import annotations

from dataclasses import replace

from .models import Capabilities, ControlResult, PlaybackSnapshot, PlaybackStatus, Track


class MockSpotifyAdapter:
    def __init__(self) -> None:
        self.state = PlaybackSnapshot(
            Track("Fictional Sunrise", "Example Artist", "Synthetic Album", 180_000),
            PlaybackStatus.PLAYING, 30_000,
            Capabilities(seek=True, next=True, previous=True, play=True, pause=True),
            connection_id=1, track_revision=1,
        )
        self.calls: list[tuple[str, int | None]] = []
        self.fail: set[str] = set()

    def snapshot(self) -> PlaybackSnapshot:
        return self.state

    def _command(self, action: str, position: int | None = None) -> ControlResult:
        self.calls.append((action, position))
        if not self.state.connected:
            return ControlResult(action, False, "not_connected")
        capability = "seek" if action == "seek_zero" else action
        if not getattr(self.state.capabilities, capability):
            return ControlResult(action, False, "not_supported")
        if action in self.fail:
            return ControlResult(action, False, "command_rejected")
        if action in {"play", "pause"}:
            status = PlaybackStatus.PLAYING if action == "play" else PlaybackStatus.PAUSED
            self.state = replace(self.state, status=status)
        elif action in {"next", "previous"}:
            assert self.state.track is not None
            self.state = replace(self.state, track=replace(self.state.track, title=f"Fictional {action}"),
                                 position_ms=0, track_revision=self.state.track_revision + 1)
        else:
            self.state = replace(self.state, position_ms=position or 0)
        return ControlResult(action, True, detail="Mock only; not Windows verification")

    def play(self) -> ControlResult:
        return self._command("play")

    def pause(self) -> ControlResult:
        return self._command("pause")

    def next(self) -> ControlResult:
        return self._command("next")

    def previous(self) -> ControlResult:
        return self._command("previous")

    def seek(self, position_ms: int) -> ControlResult:
        return self._command("seek_zero" if position_ms == 0 else "seek", position_ms)

    def close(self) -> None:
        self.state = PlaybackSnapshot(connection_id=self.state.connection_id + 1)
