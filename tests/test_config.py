"""Settings from the configuration file and the environment."""

import logging
from pathlib import Path
from typing import Any, Callable

import pytest

from smartthings_ws.config import (
    ApplianceSettings,
    AuthSettings,
    PollingSettings,
    Settings,
    configure_logging,
    load_settings,
    parse_args,
)

ENVIRONMENT = (
    "HOST",
    "PORT",
    "DEV_MODE",
    "POLLING_INTERVAL",
    "RESPONSE_TIMEOUT",
    "VERBOSE",
    "AUTH_ENABLED",
    "AUTH_TOKEN",
    "APPLIANCES",
)


@pytest.fixture(autouse=True)
def clean_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    """Keep the developer's environment out of the tests"""
    for name in ENVIRONMENT:
        monkeypatch.delenv(name, raising=False)


def write(tmp_path: Path, text: str) -> str:
    """A configuration file with this content"""
    path = tmp_path / "config.yaml"
    path.write_text(text, encoding="utf-8")
    return str(path)


def test_defaults_without_a_file(tmp_path: Path) -> None:
    """Test that a missing file gives the defaults"""
    assert load_settings(str(tmp_path / "missing.yaml")) == Settings()


def test_shipped_configuration() -> None:
    """Test that the configuration in the repository lists the five appliances"""
    settings = load_settings(str(Path(__file__).parent.parent / "config.yaml"))

    assert [(a.name, a.host, a.port) for a in settings.appliances] == [
        ("microwave", "192.168.50.20", 49154),
        ("fridge", "192.168.50.21", 49154),
        ("washer", "192.168.50.22", 49154),
        ("oven", "192.168.50.23", 49154),
        ("dryer", "192.168.50.24", 49154),
    ]
    assert settings.port == 8124 and not settings.auth.enabled


def test_file_values(tmp_path: Path) -> None:
    """Test that every section of the file is read"""
    path = write(
        tmp_path,
        """
server: {host: 127.0.0.1, port: 9000, dev_mode: yes}
polling: {interval: 5, response_timeout: 12.5}
logging: {verbose: true}
auth: {enabled: true, token: " abc\\n"}
appliances:
  - {name: Oven, host: 10.0.0.2, port: 5000}
  - {name: fridge, host: 10.0.0.3}
""",
    )

    assert load_settings(path) == Settings(
        host="127.0.0.1",
        port=9000,
        dev_mode=True,
        verbose=True,
        polling=PollingSettings(interval=5.0, response_timeout=12.5),
        auth=AuthSettings(enabled=True, token="abc"),
        appliances=(ApplianceSettings("oven", "10.0.0.2", 5000), ApplianceSettings("fridge", "10.0.0.3")),
    )


def test_environment_wins(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Test that the environment overrides the file, and a blank variable does not"""
    path = write(tmp_path, "server: {port: 9000, host: 10.1.1.1}\nappliances: [{name: a, host: 10.0.0.1}]\n")
    monkeypatch.setenv("PORT", "9100")
    monkeypatch.setenv("HOST", " ")
    monkeypatch.setenv("APPLIANCES", "washer=10.0.0.5, dryer = 10.0.0.6:6000")

    settings = load_settings(path)

    assert (settings.port, settings.host) == (9100, "10.1.1.1")
    assert settings.appliances == (
        ApplianceSettings("washer", "10.0.0.5"),
        ApplianceSettings("dryer", "10.0.0.6", 6000),
    )


FROM_FILE = (ApplianceSettings("a", "10.0.0.1"),)


@pytest.mark.parametrize(
    ("assignment", "read", "expected"),
    [
        ("PORT=70000", lambda s: s.port, 9000),
        ("PORT=x", lambda s: s.port, 9000),
        ("POLLING_INTERVAL=0", lambda s: s.polling.interval, 10.0),
        ("VERBOSE=maybe", lambda s: s.verbose, False),
        ("VERBOSE=off", lambda s: s.verbose, False),
        ("DEV_MODE=on", lambda s: s.dev_mode, True),
        ("APPLIANCES=oven", lambda s: s.appliances, FROM_FILE),
        ("APPLIANCES=Bad Name=10.0.0.9", lambda s: s.appliances, FROM_FILE),
        ("APPLIANCES=a=1.1.1.1,a=2.2.2.2", lambda s: s.appliances, FROM_FILE),
        ("APPLIANCES=a=1.1.1.1:0", lambda s: s.appliances, FROM_FILE),
    ],
)
def test_unusable_environment_falls_back_to_the_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, assignment: str, read: Callable[[Settings], Any], expected: Any
) -> None:
    """Test that an unusable variable is ignored in favour of the file"""
    path = write(tmp_path, "server: {port: 9000}\nappliances: [{name: a, host: 10.0.0.1}]\n")
    variable, _, value = assignment.partition("=")
    monkeypatch.setenv(variable, value)

    assert read(load_settings(path)) == expected


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("oven=10.0.0.2", ApplianceSettings("oven", "10.0.0.2")),
        ("oven=10.0.0.2:5000", ApplianceSettings("oven", "10.0.0.2", 5000)),
        ("oven=fe80::1", ApplianceSettings("oven", "fe80::1")),
        ("oven=[fe80::1]", ApplianceSettings("oven", "fe80::1")),
        ("oven=[fe80::1]:5000", ApplianceSettings("oven", "fe80::1", 5000)),
        ("oven=oven.lan:5000", ApplianceSettings("oven", "oven.lan", 5000)),
    ],
)
def test_appliance_addresses_in_the_environment(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, text: str, expected: ApplianceSettings
) -> None:
    """Test that hosts with and without a port, IPv6 included, are read from the environment"""
    monkeypatch.setenv("APPLIANCES", text)

    assert load_settings(str(tmp_path / "missing.yaml")).appliances == (expected,)


def test_ipv6_host_in_the_file(tmp_path: Path) -> None:
    """Test that a file entry takes the host as written, colons included"""
    settings = load_settings(write(tmp_path, "appliances: [{name: oven, host: 'fe80::1', port: 5000}]\n"))

    assert settings.appliances == (ApplianceSettings("oven", "fe80::1", 5000),)


def test_appliances_as_text_in_the_file(tmp_path: Path) -> None:
    """Test that the file may list the appliances the way the environment does"""
    settings = load_settings(write(tmp_path, "appliances: oven=10.0.0.2\n"))

    assert settings.appliances == (ApplianceSettings("oven", "10.0.0.2"),)


@pytest.mark.parametrize(
    "appliances",
    ["appliances: {name: a}", "appliances: [{name: a}]", "appliances: [name]", "appliances: [{name: '', host: h}]"],
)
def test_unusable_appliances(tmp_path: Path, appliances: str) -> None:
    """Test that a malformed appliance list is ignored"""
    assert not load_settings(write(tmp_path, appliances)).appliances


@pytest.mark.parametrize("text", ["- just\n- a list\n", "server: [1]\n", "server: {port: [\n"])
def test_unusable_file(tmp_path: Path, text: str) -> None:
    """Test that a file without a usable mapping gives the defaults"""
    assert load_settings(write(tmp_path, text)) == Settings()


def test_unreadable_file(tmp_path: Path) -> None:
    """Test that a path that cannot be read as a file gives the defaults"""
    path = tmp_path / "config.yaml"
    path.mkdir()
    (path / "inner").write_text("x")

    assert load_settings(str(path)) == Settings()


def test_auth_without_token_is_refused(tmp_path: Path) -> None:
    """Test that enabling authorisation without a token refuses to start"""
    with pytest.raises(ValueError, match="auth.token is empty"):
        load_settings(write(tmp_path, "auth: {enabled: true}\n"))


def test_token_without_auth(tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
    """Test that a token with authorisation disabled is warned about"""
    assert not load_settings(write(tmp_path, "auth: {token: abc}\n")).auth.enabled
    assert "open to anyone" in caplog.text


@pytest.mark.parametrize(("argv", "expected"), [([], "config.yaml"), (["--config", "x.yaml", "--reload"], "x.yaml")])
def test_parse_args(argv: list[str], expected: str) -> None:
    """Test that only --config is read from the command line"""
    assert parse_args(argv).config == expected


def test_configure_logging() -> None:
    """Test that verbose logging includes the library's debug output"""
    configure_logging(Settings(verbose=True))
    assert logging.getLogger("smartthings_local").level == logging.DEBUG
    configure_logging(Settings())
    assert logging.getLogger("smartthings_local").level == logging.WARNING
