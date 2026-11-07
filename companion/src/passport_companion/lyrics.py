"""Strict, synchronous LRCLIB access; run lookups in the caller's worker.

Only /api/get is used. No lyrics are written to disk or logged. The urllib
socket timeout and checks between reads are not a hard total deadline: DNS and
an individual blocking read can exceed it. A stalled worker must not own the
playback/control executor. Rate-limit cooldowns never cause a blocking sleep;
ordinary request pacing can sleep for at most one second.
"""
from __future__ import annotations

import bisect
from collections import OrderedDict
from dataclasses import dataclass, field
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from fractions import Fraction
from http.client import HTTPException
import json
import math
import random
import re
import socket
import threading
import time
from typing import Any, Callable
import unicodedata
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import HTTPRedirectHandler, Request, build_opener

from .models import Track


MAX_LRC_CHARS = 262_144
MAX_LRC_LINE_CHARS = 4_096
MAX_LRC_LINES = 8_192
MAX_LYRIC_EVENTS = 10_000
MAX_METADATA_CHARS = 512
MAX_RETRY_HEADER_CHARS = 512
_PROCESS_RATE_LIMIT_DISABLED = threading.Event()
_TIMESTAMP = re.compile(r"\[([0-9]{1,3}):([0-5][0-9])(?:\.([0-9]{1,3}))?\]")
_OFFSET = re.compile(r"^\[offset:([+-]?[0-9]{1,8})\]$", re.IGNORECASE)
_ENDPOINT = "https://lrclib.net/api/get"
_DEFAULT_USER_AGENT = "PassportCompanion/0.1.0 (https://github.com/FoloToy/ai-passport)"


@dataclass(frozen=True, slots=True)
class LyricLine:
    at_ms: int
    text: str


@dataclass(frozen=True, slots=True)
class LyricPair:
    current: str = ""
    next: str = ""
    current_at_ms: int | None = None


@dataclass(frozen=True, slots=True)
class LyricsResult:
    status: str
    detail: str = ""
    lines: tuple[LyricLine, ...] = field(default=(), repr=False)
    _times: tuple[int, ...] = field(init=False, repr=False, compare=False)

    def __post_init__(self) -> None:
        object.__setattr__(self, "_times", tuple(line.at_ms for line in self.lines))

    def at(self, position_ms: int) -> LyricPair:
        """Select without playback state; rewinds and repeated paused positions work."""
        if self.status != "synced" or not self.lines:
            return LyricPair()
        index = bisect.bisect_right(self._times, position_ms) - 1
        if index < 0:
            return LyricPair(next=self.lines[0].text)
        current = self.lines[index]
        following = self.lines[index + 1].text if index + 1 < len(self.lines) else ""
        return LyricPair(current.text, following, current.at_ms)


def parse_lrc(text: str) -> tuple[LyricLine, ...]:
    """Parse bounded LRC, retaining empty timed lines as intentional clear events.

    The last valid global offset applies to every event, including earlier ones.
    Negative adjusted times clamp to zero. At a duplicate adjusted timestamp the
    last source occurrence wins, including an empty line. Malformed/untimed lines
    are ignored; exceeding a resource cap raises ValueError instead of truncating.
    """
    if not isinstance(text, str):
        raise TypeError("LRC must be a string")
    if len(text) > MAX_LRC_CHARS:
        raise ValueError("LRC text is too large")
    if any(0xD800 <= ord(char) <= 0xDFFF for char in text):
        raise ValueError("LRC contains invalid Unicode surrogates")
    source = text.removeprefix("\ufeff").splitlines()
    if len(source) > MAX_LRC_LINES:
        raise ValueError("Too many LRC lines")
    events: list[tuple[int, str]] = []
    offset = 0
    for raw in source:
        if len(raw) > MAX_LRC_LINE_CHARS:
            raise ValueError("LRC line is too large")
        line = raw.strip()
        offset_match = _OFFSET.fullmatch(line)
        if offset_match:
            candidate = int(offset_match[1])
            if abs(candidate) <= 3_600_000:
                offset = candidate
            continue
        times: list[int] = []
        cursor = 0
        while match := _TIMESTAMP.match(line, cursor):
            minutes, seconds, fraction = match.groups()
            times.append((int(minutes) * 60 + int(seconds)) * 1000
                         + int((fraction or "0").ljust(3, "0")))
            cursor = match.end()
            while cursor < len(line) and line[cursor].isspace():
                cursor += 1
        if not times:
            continue
        lyric = line[cursor:].strip()
        # Do not turn a partly malformed multi-tag prefix into displayed lyrics.
        if re.match(r"\[[0-9]", lyric):
            continue
        if len(events) + len(times) > MAX_LYRIC_EVENTS:
            raise ValueError("Too many timed LRC events")
        events.extend((stamp, lyric) for stamp in times)
    by_time = {max(0, stamp + offset): lyric for stamp, lyric in events}
    return tuple(LyricLine(stamp, by_time[stamp]) for stamp in sorted(by_time))


def _normalize(value: str) -> str:
    return " ".join(unicodedata.normalize("NFKC", value).casefold().split())


def _metadata(value: object, *, required: bool) -> str:
    if (not isinstance(value, str) or len(value) > MAX_METADATA_CHARS or "\x00" in value
            or any(0xD800 <= ord(char) <= 0xDFFF for char in value)):
        raise ValueError("Invalid or oversized track metadata")
    normalized = _normalize(value)
    if len(normalized) > MAX_METADATA_CHARS or (required and not normalized):
        raise ValueError("Missing or oversized track metadata")
    return normalized


def _bounded_number(name: str, value: float, minimum: float, maximum: float) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{name} must be a finite number")
    if not math.isfinite(value) or not minimum <= value <= maximum:
        raise ValueError(f"{name} is outside its supported bounds")
    return float(value)


class _NoRedirects(HTTPRedirectHandler):
    def redirect_request(self, req: Any, fp: Any, code: int, msg: str,
                         headers: Any, newurl: str) -> None:
        return None


class LyricsAdapter:
    """Bounded, thread-serialized LRCLIB adapter with monotonic in-memory LRU TTLs.

    Inject ``opener(request, timeout=seconds)``, ``clock`` (monotonic), ``sleep``,
    ``wall_clock`` (only for HTTP-date Retry-After), and ``jitter`` returning 0..1
    for offline tests. An OpenerDirector with .open is accepted too. Injected
    transports must respect the timeout and bounded read contract. Retry-After
    seconds and HTTP dates are honored in full, with nonnegative jitter and
    monotonic deadlines rounded upward, never shortened. Headers over 512 chars
    or deadlines that cannot be represented finitely disable network access for
    the process lifetime (cached successes remain usable). Cooldowns never sleep.
    Metadata matching never strips punctuation, drops album, or uses search.
    """

    def __init__(
        self, *, opener: Any = None, clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
        wall_clock: Callable[[], float] = time.time,
        jitter: Callable[[], float] = random.random,
        timeout: float = 5.0, cache_size: int = 64,
        positive_ttl: float = 3_600.0, negative_ttl: float = 120.0,
        failure_ttl: float = 5.0, min_interval: float = 0.25,
        max_response_bytes: int = 1_048_576,
        user_agent: str = _DEFAULT_USER_AGENT,
    ) -> None:
        self.timeout = _bounded_number("timeout", timeout, 0.01, 30.0)
        self.positive_ttl = _bounded_number("positive_ttl", positive_ttl, 0.001, 86_400)
        self.negative_ttl = _bounded_number("negative_ttl", negative_ttl, 0.001, 3_600)
        self.failure_ttl = _bounded_number("failure_ttl", failure_ttl, 0.001, 60)
        self.min_interval = _bounded_number("min_interval", min_interval, 0.25, 1.0)
        if type(cache_size) is not int or not 1 <= cache_size <= 256:
            raise ValueError("cache_size must be between 1 and 256")
        if type(max_response_bytes) is not int or not 1 <= max_response_bytes <= 4_194_304:
            raise ValueError("max_response_bytes must be between 1 and 4194304")
        if (not isinstance(user_agent, str) or not 1 <= len(user_agent) <= 512
                or any(ord(char) < 32 or ord(char) > 126 for char in user_agent)):
            raise ValueError("user_agent must be bounded printable ASCII")
        self.cache_size = cache_size
        self.max_response_bytes = max_response_bytes
        self.user_agent = user_agent
        transport = opener if opener is not None else build_opener(_NoRedirects())
        self._open = getattr(transport, "open", transport)
        self._clock, self._sleep = clock, sleep
        self._wall_clock, self._jitter = wall_clock, jitter
        self._cache: OrderedDict[tuple[str, str, str, int], tuple[float, LyricsResult]] = OrderedDict()
        self._next_request = float("-inf")
        self._cooldown = float("-inf")
        self._lock = threading.Lock()

    def lookup(self, track: Track) -> LyricsResult:
        try:
            title = _metadata(track.title, required=True)
            artist = _metadata(track.artist, required=True)
            album = _metadata(track.album, required=False)
            duration = track.duration_ms
            if type(duration) is not int or not 1_000 <= duration <= 3_600_000:
                raise ValueError("A known duration between 1 and 3600 seconds is required")
        except (AttributeError, ValueError):
            return LyricsResult("invalid", "Missing, invalid, or oversized track metadata/duration.")
        key = title, artist, album, duration
        with self._lock:
            now = self._clock()
            # Sweep expired entries without promoting old negative results indefinitely.
            for expired in [item for item, (expiry, _) in self._cache.items() if expiry <= now]:
                del self._cache[expired]
            cached = self._cache.get(key)
            if cached is not None:
                self._cache.move_to_end(key)
                return cached[1]
            if _PROCESS_RATE_LIMIT_DISABLED.is_set():
                return LyricsResult("rate_limited", "LRCLIB network access is disabled for this process lifetime.")
            if now < self._cooldown:
                return LyricsResult("rate_limited", "LRCLIB Retry-After cooldown is active.")
            delay = self._next_request - now
            if delay > 0:
                self._sleep(min(delay, self.min_interval))
                if self._clock() < self._next_request:
                    return LyricsResult("rate_limited", "Local request pacing is active.")
            self._next_request = self._clock() + self.min_interval
            params: dict[str, str | float] = {
                "track_name": title, "artist_name": artist, "duration": duration / 1000,
            }
            if album:
                params["album_name"] = album
            request = Request(_ENDPOINT + "?" + urlencode(params), headers={
                "User-Agent": self.user_agent, "Accept": "application/json",
                "Accept-Encoding": "identity",
            })
            result = self._request(request, key)
            now = self._clock()
            self._next_request = now + self.min_interval
            ttl = (self.positive_ttl if result.status == "synced" else
                   self.negative_ttl if result.status == "none" else self.failure_ttl)
            if result.status == "rate_limited":
                ttl = min(ttl, max(0.0, self._cooldown - now))
            self._cache[key] = now + ttl, result
            self._cache.move_to_end(key)
            while len(self._cache) > self.cache_size:
                self._cache.popitem(last=False)
            return result

    def _request(self, request: Request, key: tuple[str, str, str, int]) -> LyricsResult:
        response = None
        started = self._clock()
        try:
            response = self._open(request, timeout=self.timeout)
            status = response.status
            if status != 200:
                return self._http_status(status, response.headers)
            content_type = response.headers.get("Content-Type", "")
            if content_type.split(";", 1)[0].strip().lower() != "application/json":
                return LyricsResult("invalid", "LRCLIB did not return JSON content.")
            length = response.headers.get("Content-Length")
            if length is not None:
                if len(str(length)) > 20 or not str(length).isdigit():
                    return LyricsResult("invalid", "Invalid response Content-Length.")
                if int(length) > self.max_response_bytes:
                    return LyricsResult("invalid", "LRCLIB response exceeds the size limit.")
            chunks: list[bytes] = []
            total = 0
            while True:
                if self._clock() - started >= self.timeout:
                    return LyricsResult("timeout", "LRCLIB read budget expired between reads.")
                chunk = response.read(min(16_384, self.max_response_bytes + 1 - total))
                if self._clock() - started >= self.timeout:
                    return LyricsResult("timeout", "LRCLIB read budget expired during a read.")
                if not isinstance(chunk, bytes):
                    return LyricsResult("invalid", "Invalid response body type.")
                if not chunk:
                    break
                total += len(chunk)
                if total > self.max_response_bytes:
                    return LyricsResult("invalid", "LRCLIB response exceeds the size limit.")
                chunks.append(chunk)
            payload = json.loads(b"".join(chunks).decode("utf-8"), parse_constant=_reject_constant)
            return self._record(payload, key)
        except HTTPError as error:
            try:
                return self._http_status(error.code, error.headers or {})
            finally:
                error.close()
        except (TimeoutError, socket.timeout):
            return LyricsResult("timeout", "LRCLIB network operation timed out.")
        except URLError as error:
            if isinstance(error.reason, (TimeoutError, socket.timeout)):
                return LyricsResult("timeout", "LRCLIB network operation timed out.")
            return LyricsResult("network_error", "LRCLIB could not be reached.")
        except (OSError, HTTPException):
            return LyricsResult("network_error", "LRCLIB connection or response read failed.")
        except (ValueError, UnicodeError, RecursionError, OverflowError):
            return LyricsResult("invalid", "Invalid LRCLIB response data.")
        finally:
            if response is not None:
                response.close()

    def _http_status(self, status: int, headers: Any) -> LyricsResult:
        if status == 404:
            return LyricsResult("none", "not_found: LRCLIB has no matching record.")
        if status == 429:
            raw = str(headers.get("Retry-After", "1")).strip()
            deadline = self._retry_after_deadline(raw)
            if not math.isfinite(deadline):
                _PROCESS_RATE_LIMIT_DISABLED.set()
                self._cooldown = math.inf
                return LyricsResult("rate_limited", "HTTP 429: network access disabled for this process lifetime.")
            self._cooldown = max(self._cooldown, deadline)
            return LyricsResult("rate_limited", "HTTP 429: full Retry-After cooldown started.")
        return LyricsResult("http_error", f"LRCLIB returned HTTP {status}.")

    def _retry_after_deadline(self, raw: str) -> float:
        if len(raw) > MAX_RETRY_HEADER_CHARS:
            return math.inf
        delay = Fraction(1)
        if re.fullmatch(r"[0-9]+(?:\.[0-9]+)?", raw):
            delay = Fraction(raw)
        else:
            try:
                date = parsedate_to_datetime(raw)
            except (ValueError, TypeError, OverflowError):
                date = None
            if date is not None and date.tzinfo is not None:
                try:
                    # datetime subtraction avoids Windows timestamp range limits.
                    elapsed = date - datetime(1970, 1, 1, tzinfo=timezone.utc)
                    epoch_seconds = Fraction(elapsed.days * 86_400 + elapsed.seconds)
                    epoch_seconds += Fraction(elapsed.microseconds, 1_000_000)
                    delay = max(Fraction(0), epoch_seconds - Fraction(self._wall_clock()))
                except (ValueError, OverflowError, OSError):
                    return math.inf
        jitter = self._jitter()
        if not isinstance(jitter, (int, float)) or not 0 <= jitter <= 1:
            jitter = 0.0
        delay *= 1 + Fraction(3, 10) * Fraction(jitter)
        try:
            # Exact arithmetic prevents large/fractional delays rounding to an
            # earlier deadline; float conversion is rounded toward the future.
            exact_deadline = Fraction(self._clock()) + delay
            deadline = float(exact_deadline)
        except (ValueError, OverflowError):
            return math.inf
        if math.isfinite(deadline) and Fraction(deadline) < exact_deadline:
            deadline = math.nextafter(deadline, math.inf)
        return deadline

    @staticmethod
    def _record(payload: object, key: tuple[str, str, str, int]) -> LyricsResult:
        if not isinstance(payload, dict):
            return LyricsResult("invalid", "LRCLIB record is not an object.")
        title = _metadata(payload.get("trackName"), required=True)
        artist = _metadata(payload.get("artistName"), required=True)
        album_value = payload.get("albumName")
        # Omitted albums need not match, but supplied response strings are still bounded.
        album = _metadata(album_value, required=False) if album_value is not None or key[2] else ""
        if not key[2]:
            album = ""
        duration = payload.get("duration")
        if (isinstance(duration, bool) or not isinstance(duration, (int, float))
                or not math.isfinite(duration) or not 1 <= duration <= 3600):
            return LyricsResult("invalid", "LRCLIB record has no valid known duration.")
        if ((title, artist, album) != key[:3] or abs(duration * 1000 - key[3]) > 2000):
            return LyricsResult("mismatch", "LRCLIB metadata or duration does not strictly match.")
        instrumental = payload.get("instrumental")
        if type(instrumental) is not bool:
            return LyricsResult("invalid", "LRCLIB instrumental flag is invalid.")
        if instrumental:
            return LyricsResult("none", "instrumental: no lyrics are expected.")
        synced = payload.get("syncedLyrics")
        if synced is None or synced == "":
            return LyricsResult("none", "no_synced_lyrics: matching record has no timed lyrics.")
        if not isinstance(synced, str):
            return LyricsResult("invalid", "LRCLIB synced lyrics are not a string.")
        lines = parse_lrc(synced)
        if not lines or not any(line.text for line in lines):
            return LyricsResult("invalid", "LRCLIB synced lyrics contain no usable timed text.")
        return LyricsResult("synced", "Strict metadata and duration match.", lines)


def _reject_constant(value: str) -> None:
    raise ValueError("Non-finite JSON constant")
