"""The session to one appliance."""

import cbor2
import pytest

from smartthings_ws.certificate import ClientCertificate
from smartthings_ws.config import ApplianceSettings
from smartthings_ws.connection import ApplianceConnection, coap_code, local_port, parse_collection
from smartthings_ws.errors import ApplianceUnavailable, CommandRejected
from tests.conftest import BAD_REQUEST, FakeNetwork
from tests.fixtures import HOSTS


def connect(network: FakeNetwork, certificate: ClientCertificate, name: str = "washer") -> ApplianceConnection:
    """A connection to one appliance of the fake network"""
    return ApplianceConnection(ApplianceSettings(name=name, host=HOSTS[name]), certificate, 1.0, network)


async def test_read_resources(network: FakeNetwork, certificate: ClientCertificate) -> None:
    """Test that the collection read maps every href to its representation, skipping the collection itself"""
    resources = await connect(network, certificate).read_resources()

    assert resources == network["washer"].resources


async def test_session_is_kept_open(network: FakeNetwork, certificate: ClientCertificate) -> None:
    """Test that consecutive exchanges share one session and close() closes it"""
    connection = connect(network, certificate)

    await connection.read_resources()
    await connection.write("/power/0", {"value": True})
    await connection.close()

    assert network["washer"].events == ["connect", "close"]
    session = network.sessions[0]
    assert (session.port, session.local_port) == (49154, 61022)


async def test_failed_exchange_reconnects(network: FakeNetwork, certificate: ClientCertificate) -> None:
    """Test that a failed read drops the session and the next exchange opens a new one"""
    connection = connect(network, certificate)
    await connection.read_resources()

    network["washer"].unreachable = True
    with pytest.raises(ApplianceUnavailable, match="washer did not answer: TimeoutError"):
        await connection.read_resources()
    with pytest.raises(ApplianceUnavailable):
        await connection.read_resources()

    network["washer"].unreachable = False
    await connection.read_resources()

    # The broken session is closed, then the one whose handshake failed.
    assert network["washer"].events == ["connect", "close", "close", "connect"]


async def test_read_error_code(network: FakeNetwork, certificate: ClientCertificate) -> None:
    """Test that an error response to the state read is reported with its code"""
    network["washer"].get_reply = (0x84, None)

    with pytest.raises(ApplianceUnavailable, match="4.04"):
        await connect(network, certificate).read_resources()


@pytest.mark.parametrize(
    ("payload", "reason"),
    [(cbor2.dumps("Control fail, remote control off"), ": Control fail, remote control off"), (b"\xff", ": \ufffd")],
)
async def test_write_rejected(
    network: FakeNetwork, certificate: ClientCertificate, payload: bytes, reason: str
) -> None:
    """Test that a refused write raises with the appliance's code and reason"""
    network["washer"].post_reply = (BAD_REQUEST, payload)

    with pytest.raises(CommandRejected, match=f"refused the write to /power/0 with 4.00{reason}"):
        await connect(network, certificate).write("/power/0", {"value": True})


async def test_write_rejected_without_reason(network: FakeNetwork, certificate: ClientCertificate) -> None:
    """Test that a refused write without a body reports the code alone"""
    network["washer"].post_reply = (BAD_REQUEST, b"")

    with pytest.raises(CommandRejected, match=r"with 4\.00$"):
        await connect(network, certificate).write("/power/0", {"value": True})


async def test_write_sends_cbor(network: FakeNetwork, certificate: ClientCertificate) -> None:
    """Test that a write reaches the resource with its body"""
    await connect(network, certificate).write("/operational/state/vs/0", {"x": "Run"})

    assert network["washer"].posts == [("/operational/state/vs/0", {"x": "Run"})]


@pytest.mark.parametrize("body", [{"links": []}, "text", [{"href": "/a"}, {"href": "/b", "rep": {"v": 1}}, 1]])
def test_parse_collection(body: object) -> None:
    """Test that a collection read keeps only well-formed entries and rejects a non-list"""
    if not isinstance(body, list):
        with pytest.raises(ValueError):
            parse_collection(body)
    else:
        assert parse_collection(body) == {"/b": {"v": 1}}


async def test_unreadable_state(network: FakeNetwork, certificate: ClientCertificate) -> None:
    """Test that a state read whose body is not a collection is reported as unavailable"""
    network["washer"].get_reply = (0x45, {"links": []})

    with pytest.raises(ApplianceUnavailable, match="unreadable state"):
        await connect(network, certificate).read_resources()


@pytest.mark.parametrize(("host", "expected"), [("192.168.50.20", 61020), ("10.0.0.255", 61255)])
def test_local_port(host: str, expected: int) -> None:
    """Test that the source port follows the last octet of the address"""
    assert local_port(host) == expected


def test_local_port_for_a_hostname() -> None:
    """Test that a hostname gets a stable port within the range"""
    assert local_port("oven.lan") == local_port("oven.lan")
    assert 61000 <= local_port("oven.lan") <= 61255


@pytest.mark.parametrize(("code", "expected"), [(0x45, "2.05"), (0x84, "4.04"), (0xA0, "5.00")])
def test_coap_code(code: int, expected: str) -> None:
    """Test that response codes print in dotted notation"""
    assert coap_code(code) == expected
