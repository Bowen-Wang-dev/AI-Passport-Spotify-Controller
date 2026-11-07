"""Terminal-only M1 verification commands; deliberately no server."""
from __future__ import annotations

import argparse
import importlib.metadata
import json
import logging
import math
import platform
import sys
import time
from dataclasses import asdict
from itertools import count
from typing import Any

from . import __version__
from .lyrics import LyricsAdapter
from .mock import MockSpotifyAdapter
from .service import Companion
from .spotify import SpotifyUnavailable, WindowsSpotifyAdapter


def _positive_float(value: str) -> float:
    number = float(value)
    if not math.isfinite(number) or number < 0.05 or number > 60:
        raise argparse.ArgumentTypeError("Interval must be finite and between 0.05 and 60 seconds")
    return number


def _positive_int(value: str) -> int:
    number = int(value)
    if number <= 0:
        raise argparse.ArgumentTypeError("Count must be positive")
    return number


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="AI Passport M1: local Windows Spotify (no device audio)")
    parser.add_argument("--mock", action="store_true", help="Offline in-memory demo; not a real Spotify test")
    parser.add_argument("--no-lyrics", action="store_true", help="Do not contact LRCLIB")
    parser.add_argument("--json", action="store_true", help="Machine-readable JSON lines")
    parser.add_argument("--verbose", action="store_true", help="Enable diagnostic logging (no lyric bodies)")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("status", help="Current metadata, playback, cover and two lyric lines")
    sub.add_parser("doctor", help="Dependency/runtime versions and local player diagnostics")
    watch = sub.add_parser("watch", help="Watch live state; Ctrl+C exits")
    watch.add_argument("--interval", type=_positive_float, default=0.25)
    watch.add_argument("--count", type=_positive_int)
    watch.add_argument("--interactive", action="store_true", help="Windows console: U=UP, O/space=OK, D=DOWN, Q=quit")
    press = sub.add_parser("press", help="Press buttons in one process, sharing the UP window")
    press.add_argument("buttons", nargs="+", choices=["up", "ok", "down"])
    press.add_argument("--gap", type=_positive_float, default=0.1)
    return parser


def _clean(text: str) -> str:
    return "".join(c if c.isprintable() else " " for c in text)


def _time(ms: int | None) -> str:
    if ms is None:
        return "--:--"
    seconds = ms // 1000
    return f"{seconds // 60}:{seconds % 60:02}"


def _emit(value: dict[str, Any], as_json: bool) -> None:
    if as_json:
        print(json.dumps(value, ensure_ascii=True), flush=True)
        return
    if "action" in value:
        print(f"{value['action']}: {'SUCCESS' if value['ok'] else 'FAILED'} "
              f"{value.get('error') or ''} {_clean(value.get('detail', ''))}", flush=True)
        return
    if "versions" in value:
        print(json.dumps(value, ensure_ascii=True, indent=2), flush=True)
        return
    if "fatal" in value:
        print(f"FAILED: {_clean(value['fatal'])}", flush=True)
        return
    total = value["duration_ms"]
    ratio = min(1.0, max(0.0, value["position_ms"] / total)) if total else 0
    filled = int(ratio * 20)
    print(f"[{value['status']}] {_clean(value['title'])} / {_clean(value['artist'])} "
          f"| {_clean(value['album'])}")
    print(f"[{'=' * filled}{'-' * (20-filled)}] {_time(value['position_ms'])} / {_time(total)} "
          f"cover={value['artwork']['status']} ({value['artwork']['jpeg_bytes']} bytes)")
    lyrics = value["lyrics"]
    print(f"lyrics={lyrics['status']}  current: {_clean(lyrics['current'])}  next: {_clean(lyrics['next'])}")
    print(f"capabilities={value['capabilities']} error={value['error'] or 'none'}", flush=True)


def _versions() -> dict[str, str]:
    result = {"python": platform.python_version(), "windows": platform.platform(), "companion": __version__}
    for package in ("libspotifyctl", "Pillow", "pytest"):
        try:
            result[package] = importlib.metadata.version(package)
        except importlib.metadata.PackageNotFoundError:
            result[package] = "not installed"
    return result


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.WARNING,
                        format="%(levelname)s %(name)s: %(message)s")
    if args.command == "watch" and args.interactive and (sys.platform != "win32" or not sys.stdin.isatty()):
        _emit({"fatal": "Interactive watch requires a real Windows terminal"}, args.json)
        return 2
    service: Companion | None = None
    try:
        spotify = MockSpotifyAdapter() if args.mock else WindowsSpotifyAdapter()
        lyrics = None if args.no_lyrics or args.mock or args.command == "doctor" else LyricsAdapter()
        service = Companion(spotify, lyrics=lyrics)
        if args.command == "doctor":
            view = service.poll()
            # Diagnostics intentionally omit personal track metadata and lyric text.
            _emit({"versions": _versions(), "mock": args.mock, "connected": view["connected"],
                   "status": view["status"], "has_title": bool(view["title"]),
                   "has_artist": bool(view["artist"]), "has_album": bool(view["album"]),
                   "position_ms": view["position_ms"], "duration_ms": view["duration_ms"],
                   "artwork": view["artwork"], "capabilities": view["capabilities"],
                   "error": view["error"]}, args.json)
            return 0 if view["connected"] else 1
        if args.command == "status":
            service.poll()
            service.wait_for_lyrics()
            view = service.poll()
            _emit(view, args.json)
            return 0 if view["connected"] else 1
        if args.command == "press":
            success = True
            for index, button in enumerate(args.buttons):
                if index:
                    time.sleep(args.gap)
                result = service.press(button)
                success = success and result.ok
                _emit(asdict(result), args.json)
            return 0 if success else 1
        last: dict[str, Any] | None = None
        for _tick in range(args.count) if args.count else count():
            view = service.poll()
            if view != last:
                _emit(view, args.json)
                last = view
            until = time.monotonic() + args.interval
            while time.monotonic() < until:
                if args.interactive:
                    import msvcrt
                    if msvcrt.kbhit():
                        key = msvcrt.getwch().lower()
                        if key in {"\x00", "\xe0"}:
                            msvcrt.getwch()
                        elif key == "q":
                            return 0
                        elif key in {"u", "o", " ", "d"}:
                            button = {"u": "up", "o": "ok", " ": "ok", "d": "down"}[key]
                            _emit(asdict(service.press(button)), args.json)
                time.sleep(0.01)
        return 0
    except SpotifyUnavailable as exc:
        _emit({"fatal": str(exc)}, args.json)
        return 1
    except KeyboardInterrupt:
        return 0
    finally:
        if service:
            service.close()
