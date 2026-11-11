"""The REST and WebSocket API."""

import time
from typing import Any, Iterator

import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from smartthings_ws.certificate import ClientCertificate
from smartthings_ws.api import create_app
from smartthings_ws.config import AuthSettings
from tests.conftest import BAD_REQUEST, FakeNetwork, make_settings, merge_post
from tests.fixtures import DA

TOKEN = "secret-token"


def wait_until_read(client: TestClient, name: str) -> dict[str, Any]:
    """The appliance's view once polling has read it"""
    for _ in range(200):
        view: dict[str, Any] = client.get(f"/appliances/{name}").json()
        if view["available"]:
            return view
        time.sleep(0.01)
    raise AssertionError(f"{name} was never read")


@pytest.fixture(name="protected")
def fixture_protected(network: FakeNetwork, certificate: ClientCertificate) -> Iterator[TestClient]:
    """A running application requiring a token"""
    app = create_app(make_settings(auth=AuthSettings(enabled=True, token=TOKEN)), network, certificate)
    with TestClient(app) as test_client:
        yield test_client


def test_root_and_health(client: TestClient) -> None:
    """Test that the root lists the appliance names and the health probe answers"""
    assert client.get("/").json() == {
        "app": "SmartThings Local API",
        "version": "0.4.6",
        "appliances": ["microwave", "fridge", "washer", "oven", "dryer"],
    }
    assert client.get("/health").json() == {"status": "ok"}


def test_list_and_get(client: TestClient) -> None:
    """Test that appliances are listed and read one by one"""
    view = wait_until_read(client, "dryer")

    assert view["kind"] == "dryer" and view["job"] == "AIDrying" and view["host"] == "192.168.50.24"
    assert [v["name"] for v in client.get("/appliances").json()] == ["microwave", "fridge", "washer", "oven", "dryer"]


def test_get_unknown(client: TestClient) -> None:
    """Test that an unconfigured appliance is not found"""
    response = client.get("/appliances/toaster")

    assert response.status_code == 404 and response.json() == {"detail": "No appliance is configured as toaster"}


@pytest.mark.parametrize(
    ("body", "code"),
    [
        ({"rapid_cooling": True}, 204),
        ({"rapid_cooling": False}, 304),
        ({"power": True}, 422),
        ({"fridge_target": 30}, 422),
        ({"turbo": True}, 422),
    ],
)
def test_patch(client: TestClient, network: FakeNetwork, body: dict[str, Any], code: int) -> None:
    """Test that a command answers with the status that fits its outcome"""
    network["fridge"].on_post = merge_post
    wait_until_read(client, "fridge")

    assert client.patch("/appliances/fridge", json=body).status_code == code


def test_patch_rejected(client: TestClient, network: FakeNetwork) -> None:
    """Test that a command the appliance refuses is a conflict"""
    network["washer"].post_reply = (BAD_REQUEST, b"")
    wait_until_read(client, "washer")

    response = client.patch("/appliances/washer", json={"operation": "start"})

    assert response.status_code == 409 and "4.00" in response.json()["detail"]


def test_patch_unavailable(client: TestClient, network: FakeNetwork) -> None:
    """Test that a command for an appliance that never answered is a service unavailable"""
    network["oven"].unreachable = True

    assert client.patch("/appliances/oven", json={"power": True}).status_code == 503


def test_websocket_list_and_report(client: TestClient, network: FakeNetwork) -> None:
    """Test that a client gets the list on connect and changes as reports"""
    wait_until_read(client, "dryer")

    with client.websocket_connect("/ws") as ws:
        listing = ws.receive_json()
        network["dryer"].resources["/operational/state/vs/0"][DA + "progressPercentage"] = "90"
        report = ws.receive_json()

    assert listing["type"] == "list" and len(listing["data"]) == 5
    assert report == {"type": "report", "name": "dryer", "data": {"progress": {"old": 57, "new": 90}}}


@pytest.mark.parametrize(
    ("message", "expected"),
    [
        ("not json", {"type": "error", "message": "Invalid JSON format"}),
        ("[1]", {"type": "error", "message": "A message must be a JSON object"}),
        (
            '{"type": "ping", "message_id": 1}',
            {"type": "error", "message_id": 1, "message": "Unsupported message type: ping"},
        ),
        (
            '{"type": "update", "message_id": 2}',
            {"type": "error", "name": None, "message_id": 2, "message": "Missing appliance name"},
        ),
        (
            '{"type": "update", "name": "toaster", "message_id": 3, "data": {}}',
            {"type": "error", "name": "toaster", "message_id": 3, "message": "No appliance is configured as toaster"},
        ),
        (
            '{"type": "update", "name": "fridge", "message_id": 4, "data": {"rapid_freezing": true}}',
            {"type": "applied", "name": "fridge", "message_id": 4, "message": "Command accepted"},
        ),
        (
            '{"type": "update", "name": "fridge", "message_id": 5, "data": {"rapid_freezing": false}}',
            {"type": "not_changed", "name": "fridge", "message_id": 5, "message": "Already in the requested state"},
        ),
    ],
)
def test_websocket_messages(client: TestClient, network: FakeNetwork, message: str, expected: dict[str, Any]) -> None:
    """Test that each client message is answered, and errors keep the connection open"""
    wait_until_read(client, "fridge")
    # Polling keeps reporting the fridge's power reading otherwise.
    network["fridge"].resources["/energy/consumption/vs/0"][DA + "instantaneousPower"] = "3"

    with client.websocket_connect("/ws") as ws:
        ws.receive_json()
        ws.send_text(message)
        answer = ws.receive_json()
        while answer["type"] == "report":
            answer = ws.receive_json()

    assert answer == expected


def test_websocket_invalid_command(client: TestClient) -> None:
    """Test that a command failing validation is reported as an error"""
    wait_until_read(client, "fridge")

    with client.websocket_connect("/ws") as ws:
        ws.receive_json()
        ws.send_json({"type": "update", "name": "fridge", "data": {"operation": "explode"}})
        answer = ws.receive_json()

    assert answer["type"] == "error" and "operation" in answer["message"]


@pytest.mark.parametrize(
    ("headers", "code"),
    [
        ({}, 401),
        ({"Authorization": "Bearer wrong"}, 401),
        ({"Authorization": f"Bearer {TOKEN}"}, 200),
        ({"X-API-Key": TOKEN}, 200),
    ],
)
def test_token_required(protected: TestClient, headers: dict[str, str], code: int) -> None:
    """Test that the API asks for the configured token"""
    assert protected.get("/appliances", headers=headers).status_code == code


def test_public_paths_without_token(protected: TestClient) -> None:
    """Test that the health probe and the schema need no token"""
    assert protected.get("/health").status_code == 200
    assert protected.get("/openapi.json").status_code == 200


@pytest.mark.parametrize(
    ("url", "headers"),
    [(f"/ws?token={TOKEN}", {}), ("/ws", {"Authorization": f"Bearer {TOKEN}"}), ("/ws", {"X-API-Key": TOKEN})],
)
def test_websocket_token(protected: TestClient, url: str, headers: dict[str, str]) -> None:
    """Test that a WebSocket presenting the token in any supported way is served"""
    with protected.websocket_connect(url, headers=headers) as ws:
        assert ws.receive_json()["type"] == "list"


@pytest.mark.parametrize("url", ["/ws", "/ws?token=wrong"])
def test_websocket_without_token(protected: TestClient, url: str) -> None:
    """Test that a WebSocket without the token is closed with a policy violation"""
    with pytest.raises(WebSocketDisconnect) as refused:
        with protected.websocket_connect(url):
            pass

    assert refused.value.code == 1008
