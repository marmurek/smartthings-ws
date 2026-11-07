"""Settings, loaded from a YAML file and overridable from the environment."""

import argparse
import logging
import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Optional, Sequence

import yaml

logger = logging.getLogger(__name__)

DEFAULT_CONFIG_PATH = "config.yaml"

# The OCF secure port the appliances tested advertise in /oic/res.
DEFAULT_APPLIANCE_PORT = 49154

# Appliance names appear in URLs, so they are restricted to a URL-safe slug.
NAME_PATTERN = re.compile(r"[a-z0-9][a-z0-9_-]*")


@dataclass(frozen=True)
class AuthSettings:
    """Shared token authorisation, off unless a token is configured"""

    enabled: bool = False
    token: str = ""


@dataclass(frozen=True)
class ApplianceSettings:
    """One appliance the service talks to"""

    name: str
    host: str
    port: int = DEFAULT_APPLIANCE_PORT


@dataclass(frozen=True)
class PollingSettings:
    """How often and how patiently the appliances are read"""

    interval: float = 10.0
    response_timeout: float = 30.0


@dataclass(frozen=True)
class Settings:
    """Everything the application can be configured with"""

    host: str = "0.0.0.0"
    port: int = 8124
    dev_mode: bool = False
    verbose: bool = False
    polling: PollingSettings = field(default_factory=PollingSettings)
    auth: AuthSettings = field(default_factory=AuthSettings)
    appliances: tuple[ApplianceSettings, ...] = ()


TRUE_WORDS = frozenset({"1", "true", "yes", "on"})
FALSE_WORDS = frozenset({"0", "false", "no", "off"})


def _as_bool(value: Any) -> bool:
    """Read a boolean the way both YAML and an environment variable spell it"""
    if isinstance(value, bool):
        return value

    word = str(value).strip().lower()
    if word in TRUE_WORDS:
        return True
    if word in FALSE_WORDS:
        return False
    raise ValueError(f"{value!r} is not a boolean")


def _within(minimum: float, maximum: Optional[float], cast: Callable[[Any], Any]) -> Callable[[Any], Any]:
    """A cast that also refuses values outside a sensible range"""

    def convert(value: Any) -> Any:
        result = cast(value)
        if result < minimum or (maximum is not None and result > maximum):
            raise ValueError(f"{result} is outside {minimum}..{maximum if maximum is not None else 'inf'}")
        return result

    return convert


def _text(value: Any) -> str:
    """A setting that has to be a non-empty string"""
    text = str(value).strip()
    if not text:
        raise ValueError("the value is empty")
    return text


def _appliance(name: Any, host: Any, port: Any = DEFAULT_APPLIANCE_PORT) -> ApplianceSettings:
    """One appliance, with its name checked to be usable in a URL"""
    slug = _text(name).lower()
    if not NAME_PATTERN.fullmatch(slug):
        raise ValueError(f"appliance name {slug!r} may only contain a-z, 0-9, '-' and '_'")
    return ApplianceSettings(name=slug, host=_text(host), port=_within(1, 65535, int)(port))


def _appliances(value: Any) -> tuple[ApplianceSettings, ...]:
    """The appliances: a list of mappings, or comma separated `name=host[:port]` pairs"""
    if isinstance(value, str):
        return _appliances_from_text(value)
    if not isinstance(value, list):
        raise ValueError("appliances must be a list")

    result = []
    for entry in value:
        if not isinstance(entry, dict) or "name" not in entry or "host" not in entry:
            raise ValueError(f"appliance entry {entry!r} needs a name and a host")
        result.append(_appliance(entry["name"], entry["host"], entry.get("port", DEFAULT_APPLIANCE_PORT)))
    return _unique(result)


def _appliances_from_text(value: str) -> tuple[ApplianceSettings, ...]:
    """Comma separated `name=host[:port]` pairs.

    The port is split off at the last colon, so an IPv6 host needs brackets
    and a port: `oven=[fe80::1]:49154`.
    """
    result = []
    for item in value.split(","):
        name, separator, address = item.partition("=")
        if not separator:
            raise ValueError(f"{item.strip()!r} is not name=host[:port]")
        host, colon, port = address.strip().rpartition(":")
        if not colon or (":" in host and not host.endswith("]")):
            result.append(_appliance(name, address.strip().removeprefix("[").removesuffix("]")))
        else:
            result.append(_appliance(name, host.removeprefix("[").removesuffix("]"), port))
    return _unique(result)


def _unique(appliances: list[ApplianceSettings]) -> tuple[ApplianceSettings, ...]:
    """Refuse two appliances sharing a name, which would make one unreachable"""
    names = [a.name for a in appliances]
    duplicates = sorted({n for n in names if names.count(n) > 1})
    if duplicates:
        raise ValueError(f"duplicate appliance names: {', '.join(duplicates)}")
    return tuple(appliances)


def _section(document: dict[str, Any], name: str) -> dict[str, Any]:
    """One section of the configuration file, empty if it is absent"""
    section = document.get(name)
    if section is None:
        return {}
    if isinstance(section, dict):
        return section

    logger.warning("Section %r in the configuration file is not a mapping, ignoring it", name)
    return {}


def _from_environment(env: str) -> Optional[str]:
    """An environment variable's value, treating a blank one as unset.

    Compose writes `- PORT=` as an empty string, which must not override the
    configuration file.
    """
    value = os.environ.get(env)
    return value if value is not None and value.strip() else None


def _setting(section: dict[str, Any], key: str, env: str, cast: Callable[[Any], Any], default: Any) -> Any:
    """Resolve one setting: the environment wins over the file, which wins over the default.

    An unusable value is skipped rather than fatal, and the next source down is
    tried.
    """
    candidates = []

    override = _from_environment(env)
    if override is not None:
        candidates.append((override, f"environment variable {env}"))
    if key in section:
        candidates.append((section[key], f"'{key}' in the configuration file"))

    for value, source in candidates:
        try:
            return cast(value)
        except (TypeError, ValueError) as e:
            logger.warning("Ignoring %s: %s", source, e)

    return default


def _read_document(path: str) -> dict[str, Any]:
    """The configuration file's top-level mapping, empty if there is none"""
    config_path = Path(path)
    if not config_path.is_file():
        logger.info("No configuration file at %s, using defaults and the environment", path)
        return {}

    try:
        document = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError as e:
        logger.error("Could not parse %s, using defaults and the environment: %s", path, e)
        return {}
    except OSError as e:
        # A file mounted into the container may not be readable by the
        # unprivileged user the application runs as.
        logger.error("Could not read %s, using defaults and the environment: %s", path, e)
        return {}

    if not isinstance(document, dict):
        logger.error("%s does not contain a mapping, using defaults and the environment", path)
        return {}
    return document


def load_settings(path: str = DEFAULT_CONFIG_PATH) -> Settings:
    """Read the configuration file, letting the environment override it"""
    document = _read_document(path)

    server = _section(document, "server")
    polling = _section(document, "polling")
    logs = _section(document, "logging")
    auth = _section(document, "auth")

    # A token pasted from a file or a secret usually arrives with a newline.
    token = str(_setting(auth, "token", "AUTH_TOKEN", str, "") or "").strip()
    enabled = _setting(auth, "enabled", "AUTH_ENABLED", _as_bool, False)

    if enabled and not token:
        logger.error("Authorisation is enabled but no token is configured; refusing to run unprotected")
        raise ValueError("auth.enabled is true but auth.token is empty")

    if token and not enabled:
        logger.warning("A token is configured but auth.enabled is false, so the API is open to anyone")

    appliances = _setting(document, "appliances", "APPLIANCES", _appliances, ())
    if not appliances:
        logger.warning("No appliances are configured")

    return Settings(
        host=_setting(server, "host", "HOST", _text, "0.0.0.0"),
        port=_setting(server, "port", "PORT", _within(1, 65535, int), 8124),
        dev_mode=_setting(server, "dev_mode", "DEV_MODE", _as_bool, False),
        verbose=_setting(logs, "verbose", "VERBOSE", _as_bool, False),
        polling=PollingSettings(
            interval=_setting(polling, "interval", "POLLING_INTERVAL", _within(1, None, float), 10.0),
            response_timeout=_setting(polling, "response_timeout", "RESPONSE_TIMEOUT", _within(1, None, float), 30.0),
        ),
        auth=AuthSettings(enabled=enabled, token=token),
        appliances=appliances,
    )


def parse_args(argv: Optional[Sequence[str]] = None) -> argparse.Namespace:
    """Parse the command line, which only says where the configuration lives.

    Unknown arguments are ignored so the module can also be imported by a server
    started with its own command line, such as `uvicorn main:app`.
    """
    parser = argparse.ArgumentParser(add_help=False)
    parser.description = "SmartThings Local API - REST and WebSocket API for Samsung appliances"
    parser.add_argument("--config", help="Path to the YAML configuration file", default=DEFAULT_CONFIG_PATH)

    args, _unknown = parser.parse_known_args(argv)
    return args


def configure_logging(settings: Settings) -> None:
    """Set the log levels for the application and for smartthings-local"""
    logging.basicConfig(level=logging.INFO)
    logging.getLogger().setLevel(logging.DEBUG if settings.verbose else logging.INFO)
    logging.getLogger("smartthings_local").setLevel(logging.DEBUG if settings.verbose else logging.WARNING)
