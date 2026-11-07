"""Host-side values; no device, network server or audio data structures."""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Protocol


class PlaybackStatus(str, Enum):
    PLAYING = "playing"
    PAUSED = "paused"
    STOPPED = "stopped"
    CHANGING = "changing_track"
    DISCONNECTED = "disconnected"
    AD = "ad"


@dataclass(frozen=True)
class Track:
    title: str
    artist: str
    album: str
    duration_ms: int | None

    @property
    def key(self) -> tuple[str, str, str, int | None]:
        return self.title, self.artist, self.album, self.duration_ms


@dataclass(frozen=True)
class Capabilities:
    seek: bool = False
    next: bool = False
    previous: bool = False
    play: bool = False
    pause: bool = False


@dataclass(frozen=True)
class PlaybackSnapshot:
    track: Track | None = None
    status: PlaybackStatus = PlaybackStatus.DISCONNECTED
    position_ms: int = 0
    capabilities: Capabilities = field(default_factory=Capabilities)
    artwork: bytes = field(default=b"", repr=False)
    connection_id: int = 0
    track_revision: int = 0
    error: str | None = None

    @property
    def connected(self) -> bool:
        return self.status != PlaybackStatus.DISCONNECTED

    @property
    def identity(self) -> tuple[object, ...] | None:
        if not self.connected or self.track is None:
            return None
        return self.connection_id, self.track_revision, self.track.key


@dataclass(frozen=True)
class ControlResult:
    action: str
    ok: bool
    error: str | None = None
    detail: str = ""


class SpotifyAdapter(Protocol):
    def snapshot(self) -> PlaybackSnapshot: ...
    def play(self) -> ControlResult: ...
    def pause(self) -> ControlResult: ...
    def next(self) -> ControlResult: ...
    def previous(self) -> ControlResult: ...
    def seek(self, position_ms: int) -> ControlResult: ...
    def close(self) -> None: ...
