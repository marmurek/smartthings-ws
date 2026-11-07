"""The Docker health check."""

import urllib.error
from pathlib import Path
from typing import Any

import pytest

from smartthings_ws import probe
from smartthings_ws.config import Settings


@pytest.mark.parametrize(
    ("host", "expected"),
    [
        ("0.0.0.0", "127.0.0.1:8180"),
        ("*", "127.0.0.1:8180"),
        ("::", "[::1]:8180"),
        ("192.168.50.10", "192.168.50.10:8180"),
        ("fe80::1", "[fe80::1]:8180"),
        ("[fe80::1]", "[fe80::1]:8180"),
    ],
)
def test_probe_address(host: str, expected: str) -> None:
    """Test that a wildcard is probed over loopback and a named interface directly"""
    assert probe.probe_address(Settings(host=host, port=8180)) == expected


class Answer:
    """A urlopen result with a status"""

    def __init__(self, status: int) -> None:
        self.status = status

    def __enter__(self) -> "Answer":
        return self

    def __exit__(self, *_args: Any) -> None:
        return None


@pytest.mark.parametrize(("answer", "expected"), [(Answer(200), 0), (Answer(500), 1), (OSError("refused"), 1)])
def test_main(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, answer: Answer | OSError, expected: int) -> None:
    """Test that the probe succeeds only on a 200 from /health at the configured port"""
    config = tmp_path / "config.yaml"
    config.write_text("server:\n  port: 9001\n", encoding="utf-8")
    monkeypatch.setenv("CONFIG_FILE", str(config))
    requested: list[str] = []

    def urlopen(url: str, timeout: float) -> Answer:
        requested.append(url)
        assert timeout > 0
        if isinstance(answer, OSError):
            raise urllib.error.URLError(answer)
        return answer

    monkeypatch.setattr("urllib.request.urlopen", urlopen)

    assert probe.main() == expected
    assert requested == ["http://127.0.0.1:9001/health"]
