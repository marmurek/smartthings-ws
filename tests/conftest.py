"""Shared fixtures: a fake network of appliances behind the session interface."""

from dataclasses import dataclass, field
from typing import Any, Callable, Iterable, Iterator, Optional, Sequence

import cbor2
import pytest
from fastapi.testclient import TestClient

from smartthings_ws.api import create_app
from smartthings_ws.certificate import ClientCertificate, mint_client_certificate
from smartthings_ws.config import ApplianceSettings, PollingSettings, Settings
from smartthings_ws.connection import Resources
from tests.fixtures import HOSTS, resources

CONTENT = 0x45  # 2.05
CHANGED = 0x44  # 2.04
BAD_REQUEST = 0x80  # 4.00


@dataclass
class FakeAppliance:
    """One appliance on the fake network"""

    resources: Resources
    # The code and body answering the state read instead of the collection;
    # a body of None is sent as an empty payload.
    get_reply: Optional[tuple[int, Any]] = None
    post_reply: tuple[int, bytes] = (CHANGED, b"")
    unreachable: bool = False
    posts: list[tuple[str, dict[str, Any]]] = field(default_factory=list)
    # "connect" and "close", in the order the sessions did them.
    events: list[str] = field(default_factory=list)
    # Applies an accepted write to `resources`, standing in for the appliance.
    on_post: Optional[Callable[[Resources, str, dict[str, Any]], None]] = None


@dataclass
class FakeObservation:
    """Observing one appliance of the fake network"""

    # The hrefs of every Observe registration, and of every renewal.
    subscribed: list[str] = field(default_factory=list)
    renewed: list[str] = field(default_factory=list)
    # Raised by a registration instead of accepting it.
    error: Optional[Exception] = None
    # Called by the state read before it answers, e.g. to send a notification.
    before_read: Optional[Callable[[], None]] = None


@dataclass(frozen=True)
class Delivery:
    """The part of an ObserveDelivery the application reads"""

    href: str
    payload: bytes


class FakeSession:
    """A DtlsCoapSession answering from a FakeAppliance"""

    def __init__(
        self,
        appliance: FakeAppliance,
        observation: FakeObservation,
        address: tuple[str, int, int],
        on_observe_delivery: Optional[Callable[[Delivery], None]],
    ) -> None:
        self.appliance = appliance
        self.observation = observation
        self.host, self.port, self.local_port = address
        self.on_observe_delivery = on_observe_delivery

    def connect(self, *, timeout: Optional[float] = None) -> None:
        """Fail like a handshake that gets no answer while unreachable"""
        assert timeout is not None
        if self.appliance.unreachable:
            raise TimeoutError("handshake timed out")
        self.appliance.events.append("connect")

    def start_reader(self) -> None:
        """Nothing to start"""

    def get(self, path_segs: Sequence[str], *, timeout: float = 10.0) -> tuple[int, bytes]:
        """Answer the collection read"""
        assert list(path_segs) == ["device", "0"] and timeout > 0
        if self.appliance.unreachable:
            raise TimeoutError("read timed out")
        if self.observation.before_read is not None:
            self.observation.before_read()
        if self.appliance.get_reply is not None:
            code, reply = self.appliance.get_reply
            return code, b"" if reply is None else cbor2.dumps(reply)
        body: list[dict[str, Any]] = [{"href": None, "rep": {}}]
        body += [{"href": h, "rep": r} for h, r in self.appliance.resources.items()]
        return CONTENT, cbor2.dumps(body)

    def post(self, path_segs: Sequence[str], body_cbor: bytes, *, timeout: float = 8.0) -> tuple[int, bytes]:
        """Record a write and apply it if it is accepted"""
        assert timeout > 0
        if self.appliance.unreachable:
            raise TimeoutError("write timed out")
        href = "/" + "/".join(path_segs)
        body = cbor2.loads(body_cbor)
        self.appliance.posts.append((href, body))
        if self.appliance.post_reply[0] == CHANGED and self.appliance.on_post is not None:
            self.appliance.on_post(self.appliance.resources, href, body)
        return self.appliance.post_reply

    def subscribe(self, path_segs: Sequence[str]) -> None:
        """Record a registration"""
        if self.observation.error is not None:
            raise self.observation.error
        self.observation.subscribed.append("/" + "/".join(path_segs))

    def refresh_observes(self, paths: Iterable[Sequence[str]]) -> None:
        """Record a renewal"""
        self.observation.renewed += ["/" + "/".join(p) for p in paths]

    def close(self) -> None:
        """Count the close"""
        self.appliance.events.append("close")


class FakeNetwork:
    """The appliances by host, and the factory creating sessions to them"""

    def __init__(self) -> None:
        self.appliances: dict[str, FakeAppliance] = {
            host: FakeAppliance(resources(kind)) for kind, host in HOSTS.items()
        }
        self.observations = {host: FakeObservation() for host in HOSTS.values()}
        self.sessions: list[FakeSession] = []

    def __getitem__(self, name: str) -> FakeAppliance:
        return self.appliances[HOSTS[name]]

    def observation(self, name: str) -> FakeObservation:
        """What observing one appliance did"""
        return self.observations[HOSTS[name]]

    def notify(self, name: str, href: str, payload: Any, *, encode: bool = True) -> None:
        """Send a notification on the appliance's latest session, as its reader thread would"""
        session = [s for s in self.sessions if s.host == HOSTS[name]][-1]
        assert session.on_observe_delivery is not None
        session.on_observe_delivery(Delivery(href, cbor2.dumps(payload) if encode else payload))

    def __call__(
        self,
        host: str,
        port: int,
        *,
        auth: Any,
        local_port: int,
        on_observe_delivery: Optional[Callable[[Delivery], None]] = None,
    ) -> FakeSession:
        assert auth is not None
        session = FakeSession(
            self.appliances[host], self.observations[host], (host, port, local_port), on_observe_delivery
        )
        self.sessions.append(session)
        return session


def merge_post(resources_: Resources, href: str, body: dict[str, Any]) -> None:
    """Apply a write the way the appliances do for flat vendor resources"""
    resources_[href] = {**resources_.get(href, {}), **body}


@pytest.fixture(name="certificate", scope="session")
def fixture_certificate() -> ClientCertificate:
    """One certificate for the whole run: RSA key generation is slow"""
    return mint_client_certificate()


@pytest.fixture(name="network")
def fixture_network() -> FakeNetwork:
    """A fresh fake network with every supported appliance"""
    return FakeNetwork()


def make_settings(**overrides: Any) -> Settings:
    """Settings for every appliance of the fake network, polling fast"""
    values: dict[str, Any] = {
        "polling": PollingSettings(interval=0.01, response_timeout=1.0),
        "appliances": tuple(ApplianceSettings(name=n, host=h) for n, h in HOSTS.items()),
    }
    values.update(overrides)
    return Settings(**values)


@pytest.fixture(name="settings")
def fixture_settings() -> Settings:
    """Settings for every appliance of the fake network"""
    return make_settings()


@pytest.fixture(name="client")
def fixture_client(settings: Settings, network: FakeNetwork, certificate: ClientCertificate) -> Iterator[TestClient]:
    """A running application talking to the fake network"""
    app = create_app(settings, network, certificate)
    with TestClient(app) as test_client:
        yield test_client
