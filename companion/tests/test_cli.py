import json

import pytest

from passport_companion.cli import main
from passport_companion.spotify import SpotifyUnavailable


def test_mock_status_is_offline_and_structured(capsys):
    assert main(["--mock", "--json", "status"]) == 0
    view = json.loads(capsys.readouterr().out)
    assert view["title"] == "Fictional Sunrise"
    assert view["lyrics"]["status"] == "disabled"
    assert view["duration_ms"] == 180_000


def test_mock_up_double_in_one_process(capsys):
    assert main(["--mock", "--json", "press", "up", "up"]) == 0
    rows = [json.loads(row) for row in capsys.readouterr().out.splitlines()]
    assert [r["action"] for r in rows] == ["seek_zero", "previous"]
    assert all(row["ok"] for row in rows)


def test_bounded_watch_and_doctor(capsys):
    assert main(["--mock", "--json", "watch", "--count", "2", "--interval", "0.05"]) == 0
    assert json.loads(capsys.readouterr().out)["connected"]
    assert main(["--mock", "--json", "doctor"]) == 0
    doctor = json.loads(capsys.readouterr().out)
    assert doctor["mock"] and doctor["versions"]["companion"] == "0.1.0"
    assert "title" not in doctor


def test_unavailable_returns_failure_without_traceback(monkeypatch, capsys):
    def unavailable():
        raise SpotifyUnavailable("DLL unavailable")

    monkeypatch.setattr("passport_companion.cli.WindowsSpotifyAdapter", unavailable)
    assert main(["--json", "status"]) == 1
    assert json.loads(capsys.readouterr().out)["fatal"] == "DLL unavailable"


@pytest.mark.parametrize("option,value", [("--interval", "nan"), ("--interval", "inf"),
                                         ("--interval", "0"), ("--count", "0")])
def test_invalid_watch_arguments(option, value):
    with pytest.raises(SystemExit) as exc:
        main(["--mock", "watch", option, value])
    assert exc.value.code == 2


def test_noninteractive_terminal_rejected(monkeypatch, capsys):
    monkeypatch.setattr("sys.stdin.isatty", lambda: False)
    assert main(["--mock", "--json", "watch", "--interactive"]) == 2
    assert "Windows terminal" in json.loads(capsys.readouterr().out)["fatal"]
