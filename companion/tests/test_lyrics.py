"""Offline tests: every sentence below is original fictional test text."""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import FrozenInstanceError, replace
from datetime import datetime, timezone
from email.message import Message
from email.utils import formatdate
from fractions import Fraction
from http.client import IncompleteRead
from io import BytesIO
import json
import math
import socket
import threading
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qs, urlsplit

import pytest

from passport_companion import lyrics
from passport_companion.lyrics import (
    LyricLine, LyricPair, LyricsAdapter, LyricsResult, parse_lrc,
)
from passport_companion.models import Track


@pytest.fixture(autouse=True)
def isolate_process_rate_limit_disable(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(lyrics, "_PROCESS_RATE_LIMIT_DISABLED", threading.Event())


TRACK = Track("Clockwork Orchard", "Paper Observatory", "Glass Gardens", 120_000)
FICTIONAL_LRC = (
    "[00:01.00] A lantern floats above the garden gate.\n"
    "[00:04.50] The paper moon folds into a tiny boat.\n"
    "[00:08.000] Our copper kite rests in a silent tree."
)


class Clock:
    def __init__(self) -> None:
        self.now = 100.0
        self.sleeps: list[float] = []

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds

    def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self.advance(seconds)


def record(**changes: object) -> dict[str, object]:
    result: dict[str, object] = {
        "trackName": TRACK.title, "artistName": TRACK.artist, "albumName": TRACK.album,
        "duration": 120.0, "instrumental": False, "syncedLyrics": FICTIONAL_LRC,
        "plainLyrics": None,
    }
    result.update(changes)
    return result


class Response(BytesIO):
    def __init__(self, payload: object = None, *, status: int = 200,
                 body: bytes | None = None, headers: dict[str, str] | None = None) -> None:
        super().__init__(body if body is not None else json.dumps(payload).encode("utf-8"))
        self.status = status
        self.headers = Message()
        self.headers["Content-Type"] = "application/json; charset=utf-8"
        for name, value in (headers or {}).items():
            self.headers.replace_header(name, value) if name in self.headers else self.headers.add_header(name, value)
        self.read_sizes: list[int] = []

    def read(self, size: int = -1) -> bytes:
        self.read_sizes.append(size)
        assert size > 0, "Transport reads must always be bounded"
        return super().read(size)


class Opener:
    def __init__(self, *responses: Response | Exception) -> None:
        self.responses = list(responses)
        self.requests: list[tuple[object, float]] = []

    def __call__(self, request: object, *, timeout: float) -> Response:
        self.requests.append((request, timeout))
        assert self.responses, "Unexpected network request"
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response


def adapter(*responses: Response | Exception, **options: object) -> tuple[LyricsAdapter, Opener, Clock]:
    clock = Clock()
    opener = Opener(*responses)
    client = LyricsAdapter(opener=opener, clock=clock, sleep=clock.sleep,
                           jitter=lambda: 0.0, **options)
    return client, opener, clock


def test_lrc_multiple_timestamps_fractions_sorting_and_unicode() -> None:
    text = (
        "\ufeff[ar:Imaginary Inventor]\n"
        "[00:08.125][00:02.1]  星の庭 🌱  \n"
        "[00:01] The velvet compass points to tea.\n"
        "[00:02.12] A violet tram crosses a cloud."
    )
    assert parse_lrc(text) == (
        LyricLine(1000, "The velvet compass points to tea."),
        LyricLine(2100, "星の庭 🌱"),
        LyricLine(2120, "A violet tram crosses a cloud."),
        LyricLine(8125, "星の庭 🌱"),
    )


@pytest.mark.parametrize(("tag", "expected"), [("+250", 1250), ("-250", 750), ("-2000", 0)])
def test_lrc_global_signed_offset_even_after_events(tag: str, expected: int) -> None:
    assert parse_lrc(f"[00:01] An amber wheel hums softly.\n[offset:{tag}]") == (
        LyricLine(expected, "An amber wheel hums softly."),
    )


def test_lrc_last_valid_offset_and_clamped_duplicates_are_deterministic() -> None:
    assert parse_lrc(
        "[offset:99]\n[00:00.1] first invented line\n[00:00.2] second invented line\n"
        "[offset:-300]\n[offset:+99999999]\n[offset:bad]"
    ) == (LyricLine(0, "second invented line"),)


def test_lrc_duplicate_last_wins_and_empty_lines_clear() -> None:
    assert parse_lrc("[00:01]first fictional sentence\n[00:01]replacement sentence\n"
                     "[00:02]cleared sentence\n[00:02]   ") == (
        LyricLine(1000, "replacement sentence"), LyricLine(2000, ""),
    )


@pytest.mark.parametrize("text", [
    "plain fictional sentence", "[00:60]bad", "[00:01.1234]bad", "[-01:02]bad",
    "[00:1]bad", "[00:02,50]bad", "[00:01][00:99]bad", "[ar:fictional]", "",
])
def test_lrc_malformed_and_untimed_lines_are_ignored(text: str) -> None:
    assert parse_lrc(text) == ()


@pytest.mark.parametrize("text", [
    "x" * (lyrics.MAX_LRC_CHARS + 1),
    "x" * (lyrics.MAX_LRC_LINE_CHARS + 1),
    "\n" * (lyrics.MAX_LRC_LINES + 1),
    ("[00:01][00:02][00:03]fiction\n" * 3334),
], ids=["total-characters", "line-characters", "line-count", "timed-event-count"])
def test_lrc_resource_caps_raise_instead_of_silently_truncating(text: str) -> None:
    with pytest.raises(ValueError):
        parse_lrc(text)


def test_lrc_exact_line_limit_is_accepted() -> None:
    text = "[00:01]" + "a" * (lyrics.MAX_LRC_LINE_CHARS - 7)
    assert len(parse_lrc(text)[0].text) == lyrics.MAX_LRC_LINE_CHARS - 7


def test_lrc_non_string_is_rejected() -> None:
    with pytest.raises(TypeError):
        parse_lrc(None)  # type: ignore[arg-type]


def test_selection_is_stateless_for_seek_pause_boundaries_and_empty_events() -> None:
    result = LyricsResult("synced", lines=parse_lrc("[00:01]first scene\n[00:02]\n[00:03]last scene"))
    assert result.at(-5) == LyricPair(next="first scene")
    assert result.at(999) == LyricPair(next="first scene")
    assert result.at(1000) == LyricPair("first scene", "", 1000)
    assert result.at(2000) == LyricPair("", "last scene", 2000)
    assert result.at(9000) == LyricPair("last scene", "", 3000)
    assert result.at(1000) == result.at(1000) == LyricPair("first scene", "", 1000)
    assert LyricsResult("none").at(1000) == LyricPair()
    assert LyricsResult("invalid", lines=result.lines).at(1000) == LyricPair()


@pytest.mark.parametrize("value", [LyricLine(0, "fiction"), LyricPair(), LyricsResult("none")])
def test_public_values_are_frozen(value: object) -> None:
    name = "at_ms" if isinstance(value, LyricLine) else "current" if isinstance(value, LyricPair) else "status"
    with pytest.raises(FrozenInstanceError):
        setattr(value, name, "changed")


def test_lookup_uses_only_get_camel_case_metadata_and_finite_timeout() -> None:
    response = Response(record())
    client, opener, _ = adapter(response)
    result = client.lookup(TRACK)
    assert result.status == "synced"
    assert result.at(1000).current == "A lantern floats above the garden gate."
    request, timeout = opener.requests[0]
    url = urlsplit(request.full_url)
    assert url.scheme == "https" and url.netloc == "lrclib.net" and url.path == "/api/get"
    assert parse_qs(url.query) == {
        "track_name": ["clockwork orchard"], "artist_name": ["paper observatory"],
        "album_name": ["glass gardens"], "duration": ["120.0"],
    }
    assert "PassportCompanion/0.1.0" in request.get_header("User-agent")
    assert "https://" in request.get_header("User-agent")
    assert request.get_header("Accept-encoding") == "identity"
    assert 0 < timeout <= 30
    assert response.closed and response.read_sizes


def test_strict_normalization_is_case_unicode_and_whitespace_only() -> None:
    track = Track("  Ｓｉｌｖｅｒ\u00a0  Map ", "Cafe\u0301  Pilots", "  Blue\t Atlas ", 120_000)
    response = Response(record(trackName="silver map", artistName="CAFÉ PILOTS", albumName="blue atlas"))
    client, opener, _ = adapter(response)
    assert client.lookup(track).status == "synced"
    assert client.lookup(replace(track, title="Silver Map", artist="Café Pilots")).status == "synced"
    assert len(opener.requests) == 1


def test_album_is_omitted_only_when_caller_did_not_supply_it() -> None:
    client, opener, _ = adapter(Response(record(albumName="Different fictional album")))
    assert client.lookup(replace(TRACK, album=" \u00a0 ")).status == "synced"
    assert "album_name" not in parse_qs(urlsplit(opener.requests[0][0].full_url).query)


@pytest.mark.parametrize("changes", [
    {"trackName": "Clockwork Orchard - Live"}, {"artistName": "Another Invented Artist"},
    {"albumName": "Another Garden"}, {"albumName": ""}, {"duration": 122.001}, {"duration": 117.999},
])
def test_strict_mismatches_never_fall_back_to_search(changes: dict[str, object]) -> None:
    client, opener, _ = adapter(Response(record(**changes)))
    assert client.lookup(TRACK).status == "mismatch"
    assert len(opener.requests) == 1
    assert "/api/search" not in opener.requests[0][0].full_url


@pytest.mark.parametrize("duration", [118, 122, 120.5])
def test_duration_tolerance_includes_exact_two_second_boundary(duration: float) -> None:
    client, _, _ = adapter(Response(record(duration=duration)))
    assert client.lookup(TRACK).status == "synced"


@pytest.mark.parametrize("duration", [None, 0, -1, True, 120_000.0, "120000", 999, 3_600_001])
def test_missing_unknown_or_invalid_input_duration_never_requests(duration: object) -> None:
    client, opener, _ = adapter()
    assert client.lookup(replace(TRACK, duration_ms=duration)).status == "invalid"
    assert opener.requests == []


@pytest.mark.parametrize("changes", [
    {"title": ""}, {"artist": "   "}, {"title": "x" * 513}, {"album": "x" * 513},
    {"artist": None}, {"title": "bad\x00title"}, {"title": "bad\ud800title"},
])
def test_invalid_input_metadata_never_requests(changes: dict[str, object]) -> None:
    client, opener, _ = adapter()
    assert client.lookup(replace(TRACK, **changes)).status == "invalid"
    assert opener.requests == []


@pytest.mark.parametrize("changes", [
    {"duration": None}, {"duration": 0}, {"duration": True}, {"duration": "120"},
    {"duration": float("inf")}, {"duration": float("nan")}, {"trackName": None},
    {"artistName": "x" * 513}, {"albumName": None}, {"instrumental": "false"},
    {"syncedLyrics": 123}, {"syncedLyrics": "not timed fictional prose"},
    {"syncedLyrics": "[00:01]   "}, {"syncedLyrics": "x" * (lyrics.MAX_LRC_CHARS + 1)},
    {"syncedLyrics": "[00:01]bad\ud800unicode"},
])
def test_invalid_records_are_truthful_and_do_not_display_lyrics(changes: dict[str, object]) -> None:
    client, _, _ = adapter(Response(record(**changes)))
    result = client.lookup(TRACK)
    assert result.status == "invalid"
    assert result.at(2000) == LyricPair()


@pytest.mark.parametrize(("response", "detail"), [
    (Response(status=404), "not_found"),
    (Response(record(instrumental=True)), "instrumental"),
    (Response(record(syncedLyrics=None, plainLyrics="A fictional unclocked sentence.")), "no_synced_lyrics"),
    (Response(record(syncedLyrics="")), "no_synced_lyrics"),
])
def test_none_reasons_are_distinct(response: Response, detail: str) -> None:
    client, _, _ = adapter(response)
    result = client.lookup(TRACK)
    assert result.status == "none" and detail in result.detail
    assert result.at(5000) == LyricPair()
    assert response.closed


def test_positive_cache_expires_at_monotonic_ttl() -> None:
    client, opener, clock = adapter(Response(record()), Response(record()), positive_ttl=10)
    first = client.lookup(TRACK)
    clock.advance(9.999)
    assert client.lookup(TRACK) is first
    clock.advance(0.001)
    assert client.lookup(TRACK).status == "synced"
    assert len(opener.requests) == 2


def test_negative_cache_expiry() -> None:
    client, opener, clock = adapter(Response(status=404), Response(record()), negative_ttl=2)
    first = client.lookup(TRACK)
    clock.advance(1.999)
    assert client.lookup(TRACK) is first
    clock.advance(0.001)
    assert client.lookup(TRACK).status == "synced"
    assert len(opener.requests) == 2


def test_failures_have_short_ttl_and_do_not_become_long_negative_cache() -> None:
    client, opener, clock = adapter(URLError("offline"), Response(record()), failure_ttl=1)
    first = client.lookup(TRACK)
    assert first.status == "network_error"
    clock.advance(0.999)
    assert client.lookup(TRACK) is first
    clock.advance(0.001)
    assert client.lookup(TRACK).status == "synced"
    assert len(opener.requests) == 2


def test_lru_eviction_promotes_hits_and_bounds_positive_and_negative_entries() -> None:
    a, b, c = (replace(TRACK, title=name) for name in ("A Fiction", "B Fiction", "C Fiction"))
    client, opener, _ = adapter(Response(record(trackName=a.title)), Response(status=404),
                               Response(status=404), Response(status=404), cache_size=2)
    assert client.lookup(a).status == "synced"
    client.lookup(b)
    client.lookup(a)
    client.lookup(c)
    assert len(client._cache) == 2
    assert client.lookup(a).status == "synced"
    client.lookup(b)
    assert len(opener.requests) == 4


def test_request_pacing_is_at_least_250ms_between_distinct_keys() -> None:
    client, opener, clock = adapter(Response(status=404), Response(status=404))
    client.lookup(TRACK)
    client.lookup(replace(TRACK, title="Other Fiction"))
    assert clock.sleeps == [0.25]
    assert len(opener.requests) == 2


def test_injected_sleep_cannot_bypass_minimum_request_interval() -> None:
    clock = Clock()
    opener = Opener(Response(status=404))
    client = LyricsAdapter(opener=opener, clock=clock, sleep=lambda _: None)
    client.lookup(TRACK)
    assert client.lookup(replace(TRACK, title="Other Fiction")).status == "rate_limited"
    assert len(opener.requests) == 1


def test_parallel_lookups_are_serialized_and_each_response_is_closed() -> None:
    clock = Clock()
    request_times: list[float] = []
    responses: list[Response] = []

    def open_response(request: object, *, timeout: float) -> Response:
        assert not responses or responses[-1].closed
        request_times.append(clock())
        response = Response(status=404)
        responses.append(response)
        return response

    client = LyricsAdapter(opener=open_response, clock=clock, sleep=clock.sleep)
    with ThreadPoolExecutor(max_workers=4) as workers:
        results = list(workers.map(client.lookup, [replace(TRACK, title=f"Fiction {i}") for i in range(8)]))
    assert all(result.status == "none" for result in results)
    assert all(b - a >= 0.25 for a, b in zip(request_times, request_times[1:]))
    assert all(response.closed for response in responses)


def test_429_retry_after_with_jitter_applies_across_keys_without_sleep() -> None:
    clock = Clock()
    opener = Opener(Response(status=429, headers={"Retry-After": "10"}), Response(status=404))
    client = LyricsAdapter(opener=opener, clock=clock, sleep=clock.sleep, jitter=lambda: 0.5)
    assert client.lookup(TRACK).status == "rate_limited"
    clock.advance(11.49)
    assert client.lookup(replace(TRACK, title="Other Fiction")).status == "rate_limited"
    assert clock.sleeps == [] and len(opener.requests) == 1
    clock.advance(0.01)
    assert client.lookup(replace(TRACK, title="Other Fiction")).status == "none"
    assert len(opener.requests) == 2


@pytest.mark.parametrize(("header", "expected"), [
    ("9999999999999999999999999", 9_999_999_999_999_999_999_999_999), ("601", 601),
    ("nonsense", 1), ("-20", 1), ("0", 0), ("1.5", 1.5),
])
def test_retry_after_is_not_shortened_and_malformed_values_have_safe_default(
    header: str, expected: int | float,
) -> None:
    client, _, clock = adapter(Response(status=429, headers={"Retry-After": header}))
    assert client.lookup(TRACK).status == "rate_limited"
    exact = Fraction(clock()) + Fraction(expected)
    assert Fraction(client._cooldown) >= exact
    assert Fraction(math.nextafter(client._cooldown, -math.inf)) < exact
    assert clock.sleeps == []


def test_http_date_retry_after_uses_injected_wall_time_and_monotonic_cooldown() -> None:
    wall = 1_700_000_000.0
    client, _, clock = adapter(Response(status=429, headers={"Retry-After": formatdate(wall + 7, usegmt=True)}),
                               wall_clock=lambda: wall)
    assert client.lookup(TRACK).status == "rate_limited"
    assert client._cooldown == clock() + 7


def test_cached_success_is_available_during_global_cooldown() -> None:
    client, opener, _ = adapter(Response(record()), Response(status=429, headers={"Retry-After": "10"}))
    success = client.lookup(TRACK)
    client.lookup(replace(TRACK, title="Other Fiction"))
    assert client.lookup(TRACK) is success and len(opener.requests) == 2


def test_rate_limit_cache_does_not_outlive_short_retry_after() -> None:
    client, opener, clock = adapter(Response(status=429, headers={"Retry-After": "1"}), Response(record()))
    client.lookup(TRACK)
    clock.advance(1)
    assert client.lookup(TRACK).status == "synced" and len(opener.requests) == 2


@pytest.mark.parametrize(("error", "status"), [
    (TimeoutError("do not expose transport text"), "timeout"),
    (socket.timeout("fictional timeout"), "timeout"),
    (URLError(TimeoutError()), "timeout"), (URLError("offline"), "network_error"),
    (ConnectionResetError("private transport text"), "network_error"),
])
def test_network_failures_never_expose_transport_text(error: Exception, status: str) -> None:
    client, _, _ = adapter(error)
    result = client.lookup(TRACK)
    assert result.status == status
    assert "private" not in result.detail and "fictional" not in result.detail


@pytest.mark.parametrize("status", [400, 401, 403, 500, 503, 302])
def test_http_failures_preserve_http_status_and_close_response(status: int) -> None:
    response = Response(status=status)
    client, _, _ = adapter(response)
    result = client.lookup(TRACK)
    assert result.status == "http_error" and str(status) in result.detail and response.closed


@pytest.mark.parametrize(("code", "status"), [(404, "none"), (429, "rate_limited"), (503, "http_error")])
def test_urllib_http_errors_are_closed_and_classified(code: int, status: str) -> None:
    body = BytesIO(b"not JSON and deliberately not parsed")
    headers = Message()
    headers["Retry-After"] = "2"
    error = HTTPError("https://lrclib.net/api/get", code, "fictional rejection", headers, body)
    client, _, _ = adapter(error)
    assert client.lookup(TRACK).status == status
    assert body.closed


@pytest.mark.parametrize("response", [
    Response(body=b"not JSON"), Response(body=b"\xff"), Response([]), Response(None),
    Response(record(), headers={"Content-Type": "text/html"}),
    Response(record(), headers={"Content-Length": "invalid"}),
])
def test_invalid_http_bodies_are_rejected(response: Response) -> None:
    client, _, _ = adapter(response)
    assert client.lookup(TRACK).status == "invalid" and response.closed


def test_response_cap_is_enforced_without_content_length() -> None:
    response = Response(body=b"x" * 65)
    client, _, _ = adapter(response, max_response_bytes=64)
    assert client.lookup(TRACK).status == "invalid"
    assert response.read_sizes == [65] and response.closed


def test_oversized_content_length_prevents_any_body_read() -> None:
    response = Response(record(), headers={"Content-Length": "65"})
    client, _, _ = adapter(response, max_response_bytes=64)
    assert client.lookup(TRACK).status == "invalid"
    assert response.read_sizes == []


def test_exact_http_response_cap_is_accepted_and_length_cannot_hide_extra_bytes() -> None:
    body = json.dumps(record()).encode("utf-8")
    client, _, _ = adapter(Response(body=body), max_response_bytes=len(body))
    assert client.lookup(TRACK).status == "synced"
    client, _, _ = adapter(Response(body=body + b" ", headers={"Content-Length": str(len(body))}),
                           max_response_bytes=len(body))
    assert client.lookup(TRACK).status == "invalid"


def test_elapsed_read_budget_is_checked_after_a_blocking_read() -> None:
    clock = Clock()

    class SlowResponse(Response):
        def read(self, size: int = -1) -> bytes:
            clock.advance(6)
            return super().read(size)

    response = SlowResponse(record())
    client = LyricsAdapter(opener=Opener(response), clock=clock, sleep=clock.sleep, timeout=5)
    assert client.lookup(TRACK).status == "timeout" and response.closed


def test_response_read_failure_is_closed_and_classified() -> None:
    class BrokenResponse(Response):
        def read(self, size: int = -1) -> bytes:
            raise OSError("private source content")

    response = BrokenResponse(record())
    client, _, _ = adapter(response)
    assert client.lookup(TRACK).status == "network_error" and response.closed


@pytest.mark.parametrize("options", [
    {"cache_size": 0}, {"cache_size": 257}, {"cache_size": True}, {"timeout": 0},
    {"timeout": float("inf")}, {"timeout": 31}, {"positive_ttl": 0},
    {"negative_ttl": 3601}, {"failure_ttl": 61}, {"min_interval": 0.249},
    {"min_interval": 1.1}, {"max_response_bytes": 0},
    {"max_response_bytes": 4_194_305}, {"user_agent": "bad\r\nheader"},
])
def test_constructor_configuration_is_finite_and_bounded(options: dict[str, object]) -> None:
    with pytest.raises(ValueError):
        LyricsAdapter(**options)


def test_request_pacing_waits_after_previous_response_completion() -> None:
    clock = Clock()
    starts: list[float] = []

    def open_response(request: object, *, timeout: float) -> Response:
        starts.append(clock())
        clock.advance(0.5)
        return Response(status=404)

    client = LyricsAdapter(opener=open_response, clock=clock, sleep=clock.sleep)
    client.lookup(TRACK)
    client.lookup(replace(TRACK, title="Other Fiction"))
    assert starts == [100.0, 100.75] and clock.sleeps == [0.25]


def test_incomplete_http_transfer_returns_network_error_and_closes() -> None:
    class PartialResponse(Response):
        def read(self, size: int = -1) -> bytes:
            raise IncompleteRead(b"fictional partial body", 20)

    response = PartialResponse(record())
    client, _, _ = adapter(response)
    assert client.lookup(TRACK).status == "network_error" and response.closed


def test_optional_response_album_is_bounded_even_when_not_requested() -> None:
    client, _, _ = adapter(Response(record(albumName="x" * 513)))
    assert client.lookup(replace(TRACK, album="")).status == "invalid"


@pytest.mark.parametrize("duration_ms", [1_000, 3_600_000])
def test_api_duration_range_boundaries(duration_ms: int) -> None:
    client, _, _ = adapter(Response(record(duration=duration_ms / 1000)))
    assert client.lookup(replace(TRACK, duration_ms=duration_ms)).status == "synced"


def test_opener_director_style_injection_is_supported() -> None:
    class Director:
        def open(self, request: object, *, timeout: float) -> Response:
            return Response(record())

    assert LyricsAdapter(opener=Director()).lookup(TRACK).status == "synced"


def test_redirect_handler_refuses_to_replay_metadata_to_another_endpoint() -> None:
    handler = lyrics._NoRedirects()
    assert handler.redirect_request(None, None, 302, "redirect", {},
                                    "https://example.invalid/api/search") is None


@pytest.mark.parametrize("delay", [301, 601, 86_400])
def test_long_retry_after_blocks_all_keys_until_full_delay_without_sleep(delay: int) -> None:
    client, opener, clock = adapter(Response(status=429, headers={"Retry-After": str(delay)}),
                                    Response(status=404))
    assert client.lookup(TRACK).status == "rate_limited"
    clock.advance(300)
    assert client.lookup(TRACK).status == "rate_limited"
    clock.advance(delay - 300 - 0.25)
    other = replace(TRACK, title="Other Fiction")
    assert client.lookup(other).status == "rate_limited"
    assert len(opener.requests) == 1 and clock.sleeps == []
    clock.advance(0.25)
    assert client.lookup(other).status == "none"
    assert len(opener.requests) == 2 and clock.sleeps == []


def test_far_future_http_date_keeps_full_monotonic_deadline() -> None:
    wall = 1_700_000_000
    future = datetime(9999, 12, 31, 23, 59, 59, tzinfo=timezone.utc)
    delta = future - datetime(1970, 1, 1, tzinfo=timezone.utc)
    seconds = delta.days * 86_400 + delta.seconds - wall
    wall_values = [float(wall)]
    client, opener, clock = adapter(
        Response(status=429, headers={"Retry-After": "Fri, 31 Dec 9999 23:59:59 GMT"}),
        Response(status=404), wall_clock=lambda: wall_values[0],
    )
    assert client.lookup(TRACK).status == "rate_limited"
    assert client._cooldown == clock() + seconds
    wall_values[0] = float(wall + seconds + 1000)
    clock.advance(300)
    assert client.lookup(TRACK).status == "rate_limited"
    wall_values[0] = 0.0
    clock.advance(seconds - 301)
    other = replace(TRACK, title="Far Future Fiction")
    assert client.lookup(other).status == "rate_limited" and len(opener.requests) == 1
    assert clock.sleeps == []
    clock.advance(1)
    assert client.lookup(other).status == "none" and len(opener.requests) == 2


@pytest.mark.parametrize("header", ["9" * 600, "1" + "0" * 309],
                         ids=["overlong-header", "unrepresentable-deadline"])
def test_extreme_retry_after_disables_all_adapters_for_process_lifetime(header: str) -> None:
    client, opener, clock = adapter(Response(status=429, headers={"Retry-After": header}))
    assert client.lookup(TRACK).status == "rate_limited"
    assert client._cooldown == math.inf and lyrics._PROCESS_RATE_LIMIT_DISABLED.is_set()
    clock.advance(1e100)
    assert client.lookup(TRACK).status == "rate_limited"
    assert client.lookup(replace(TRACK, title="Other Fiction")).status == "rate_limited"
    replacement, replacement_opener, _ = adapter()
    assert replacement.lookup(TRACK).status == "rate_limited"
    assert len(opener.requests) == 1 and replacement_opener.requests == []
    assert clock.sleeps == []


def test_process_lifetime_disable_still_allows_cached_success() -> None:
    client, opener, _ = adapter(Response(record()),
                                Response(status=429, headers={"Retry-After": "9" * 600}))
    success = client.lookup(TRACK)
    assert client.lookup(replace(TRACK, title="Other Fiction")).status == "rate_limited"
    assert lyrics._PROCESS_RATE_LIMIT_DISABLED.is_set()
    assert client.lookup(TRACK) is success and len(opener.requests) == 2


@pytest.mark.parametrize("header", ["9007199254740993", "0." + "0" * 400 + "1"],
                         ids=["integer-precision", "fraction-precision"])
def test_retry_after_float_conversion_never_rounds_deadline_earlier(header: str) -> None:
    client, _, clock = adapter(Response(status=429, headers={"Retry-After": header}))
    assert client.lookup(TRACK).status == "rate_limited"
    assert Fraction(client._cooldown) >= Fraction(clock()) + Fraction(header)
    assert client._cooldown > clock()
    assert not lyrics._PROCESS_RATE_LIMIT_DISABLED.is_set()


def test_long_retry_after_preserves_positive_jitter() -> None:
    clock = Clock()
    opener = Opener(Response(status=429, headers={"Retry-After": "1000"}), Response(status=404))
    client = LyricsAdapter(opener=opener, clock=clock, sleep=clock.sleep, jitter=lambda: 0.5)
    assert client.lookup(TRACK).status == "rate_limited"
    assert client._cooldown == clock() + 1150
    clock.advance(1149)
    assert client.lookup(replace(TRACK, title="Other Fiction")).status == "rate_limited"
    assert len(opener.requests) == 1 and clock.sleeps == []
    clock.advance(1)
    assert client.lookup(replace(TRACK, title="Other Fiction")).status == "none"
