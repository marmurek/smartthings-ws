"""Polling, change reports and commands."""

import asyncio
from typing import Any

import pytest

from smartthings_ws.certificate import ClientCertificate
from smartthings_ws.errors import ApplianceNotFound, ApplianceUnavailable, CommandRejected
from smartthings_ws.manager import UNAVAILABLE_AFTER, ApplianceManager, changes_between
from smartthings_ws.models import ApplianceUpdate, MachineState
from smartthings_ws.state import read_view
from smartthings_ws.connection import Resources
from tests.conftest import BAD_REQUEST, FakeNetwork, make_settings, merge_post
from tests.fixtures import DA, resources


async def read_back(manager: ApplianceManager, name: str) -> None:
    """Wait for the read that follows a command"""
    pending = manager.appliances[name].read_back
    assert pending is not None
    await pending


async def started(network: FakeNetwork, certificate: ClientCertificate, poll: bool = False) -> ApplianceManager:
    """A manager with connections open, polling only if asked to"""
    manager = ApplianceManager(make_settings(), network, certificate)
    await manager.start()
    if not poll:
        for tracked in manager.appliances.values():
            assert tracked.task is not None
            tracked.task.cancel()
    return manager


async def test_views_before_the_first_read(network: FakeNetwork, certificate: ClientCertificate) -> None:
    """Test that every configured appliance is listed as unavailable until it has been read"""
    manager = ApplianceManager(make_settings(), network, certificate)

    assert [(v.name, v.available) for v in manager.views.values()] == [
        ("microwave", False),
        ("fridge", False),
        ("washer", False),
        ("oven", False),
        ("dryer", False),
    ]
    with pytest.raises(ApplianceNotFound):
        manager.view("toaster")
    with pytest.raises(ApplianceUnavailable, match="not connected yet"):
        await manager.refresh("oven")


async def test_polling_reads_every_appliance(network: FakeNetwork, certificate: ClientCertificate) -> None:
    """Test that polling reads every appliance and stop() closes their sessions"""
    manager = await started(network, certificate, poll=True)
    for _ in range(100):
        if all(v.available for v in manager.views.values()):
            break
        await asyncio.sleep(0.01)

    await manager.stop()

    assert manager.view("dryer").machine_state is MachineState.RUNNING
    assert all(a.events == ["connect", "close"] for a in network.appliances.values())


def test_changes_between() -> None:
    """Test that only the fields that differ are reported, as JSON values"""
    old = read_view("dryer", "10.0.0.1", resources("dryer"))
    new = old.model_copy(update={"progress": 60, "machine_state": MachineState.PAUSED})

    assert changes_between(old, new) == {
        "machine_state": {"old": "running", "new": "paused"},
        "progress": {"old": 57, "new": 60},
    }
    assert not changes_between(old, old.model_copy())


async def test_unavailable_after_repeated_failures(network: FakeNetwork, certificate: ClientCertificate) -> None:
    """Test that an appliance is reported unavailable only after several failed reads, and back after one success"""
    manager = await started(network, certificate)
    await manager.refresh("oven")
    network["oven"].unreachable = True

    for attempt in range(1, UNAVAILABLE_AFTER + 1):
        assert manager.view("oven").available
        with pytest.raises(ApplianceUnavailable):
            await manager.refresh("oven")
        assert manager.appliances["oven"].missed_reads == attempt

    assert not manager.view("oven").available
    assert manager.view("oven").power is False

    network["oven"].unreachable = False
    await manager.refresh("oven")
    assert manager.view("oven").available and manager.appliances["oven"].missed_reads == 0


async def test_send_update(network: FakeNetwork, certificate: ClientCertificate) -> None:
    """Test that a command is written and the appliance read back"""
    network["fridge"].on_post = merge_post
    manager = await started(network, certificate)
    await manager.refresh("fridge")

    assert await manager.send_update("fridge", ApplianceUpdate(rapid_freezing=True))
    await read_back(manager, "fridge")

    assert network["fridge"].posts == [("/refrigeration/vs/0", {DA + "rapidFreezing": "On"})]
    assert manager.view("fridge").rapid_freezing is True


async def test_send_update_unchanged(network: FakeNetwork, certificate: ClientCertificate) -> None:
    """Test that a command matching the state sends nothing"""
    manager = await started(network, certificate)
    await manager.refresh("fridge")

    assert not await manager.send_update("fridge", ApplianceUpdate(rapid_freezing=False))
    assert not network["fridge"].posts


async def test_send_update_before_first_read(network: FakeNetwork, certificate: ClientCertificate) -> None:
    """Test that a command for an appliance never read is refused as unavailable"""
    manager = await started(network, certificate)

    with pytest.raises(ApplianceUnavailable, match="not known yet"):
        await manager.send_update("washer", ApplianceUpdate(power=True))


async def test_send_update_rejected(network: FakeNetwork, certificate: ClientCertificate) -> None:
    """Test that a refused write stops the command"""
    network["washer"].post_reply = (BAD_REQUEST, b"")
    manager = await started(network, certificate)
    await manager.refresh("washer")

    with pytest.raises(CommandRejected):
        await manager.send_update("washer", ApplianceUpdate(power=True, operation="start"))
    assert len(network["washer"].posts) == 1


async def test_send_update_read_back_fails(network: FakeNetwork, certificate: ClientCertificate) -> None:
    """Test that a command the appliance accepted is reported as applied even if the read back fails"""
    manager = await started(network, certificate)
    await manager.refresh("washer")

    def go_offline(*_args: Any) -> None:
        network["washer"].get_reply = (0x84, None)

    network["washer"].on_post = go_offline

    assert await manager.send_update("washer", ApplianceUpdate(power=True))
    await read_back(manager, "washer")
    assert manager.appliances["washer"].missed_reads == 1


async def test_partial_command_is_read_back(network: FakeNetwork, certificate: ClientCertificate) -> None:
    """Test that the writes applied before a refused one are read back"""
    manager = await started(network, certificate)
    await manager.refresh("washer")

    def accept_once(resources_: Resources, href: str, body: dict[str, Any]) -> None:
        merge_post(resources_, href, body)
        network["washer"].post_reply = (BAD_REQUEST, b"")

    network["washer"].on_post = accept_once

    with pytest.raises(CommandRejected):
        await manager.send_update("washer", ApplianceUpdate(power=True, operation="start"))
    await read_back(manager, "washer")

    assert manager.view("washer").power is True
    assert manager.view("washer").machine_state is MachineState.IDLE


async def test_stop_cancels_a_pending_read_back(network: FakeNetwork, certificate: ClientCertificate) -> None:
    """Test that stopping the manager does not leave the read after a command running"""
    network["fridge"].on_post = merge_post
    manager = await started(network, certificate)
    await manager.refresh("fridge")

    await manager.send_update("fridge", ApplianceUpdate(rapid_cooling=True))
    await manager.stop()

    pending = manager.appliances["fridge"].read_back
    assert pending is not None and pending.done()


def record_reports(manager: ApplianceManager, monkeypatch: pytest.MonkeyPatch) -> list[dict[str, Any]]:
    """Collect what the manager broadcasts instead of sending it"""
    sent: list[dict[str, Any]] = []

    async def broadcast(data: dict[str, Any]) -> None:
        sent.append(data)

    monkeypatch.setattr(manager.connection_manager, "broadcast", broadcast)
    return sent


async def settled(manager: ApplianceManager, name: str) -> None:
    """Let the notifications already sent be applied and reported"""
    for _ in range(3):
        await asyncio.sleep(0)
    await asyncio.gather(*manager.appliances[name].notifications.reports)


async def test_read_observes_the_resources(network: FakeNetwork, certificate: ClientCertificate) -> None:
    """Test that a read observes every resource it returned"""
    manager = await started(network, certificate)

    await manager.refresh("fridge")

    assert sorted(network.observation("fridge").subscribed) == sorted(network["fridge"].resources)


async def test_notification_is_reported(
    network: FakeNetwork, certificate: ClientCertificate, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Test that a notification changes the state and is reported without a read"""
    manager = await started(network, certificate)
    await manager.refresh("fridge")
    sent = record_reports(manager, monkeypatch)

    network.notify("fridge", "/door/cooler/0", {"openState": "Open"})
    await settled(manager, "fridge")

    assert sent == [
        {
            "type": "report",
            "name": "fridge",
            "data": {"door_open": {"old": False, "new": True}, "fridge_door_open": {"old": False, "new": True}},
        }
    ]


async def test_partial_notification_is_merged(network: FakeNetwork, certificate: ClientCertificate) -> None:
    """Test that a notification carrying some keys of a resource keeps the others"""
    manager = await started(network, certificate)
    await manager.refresh("fridge")
    before = manager.view("fridge")

    network.notify("fridge", "/energy/consumption/vs/0", {DA + "cumulativePower": "500000"})
    await settled(manager, "fridge")

    assert manager.view("fridge").energy_kwh == 500.0
    assert before.energy_saved_kwh is not None
    assert manager.view("fridge").energy_saved_kwh == before.energy_saved_kwh


async def test_notification_during_a_read(network: FakeNetwork, certificate: ClientCertificate) -> None:
    """Test that a notification arriving while a read is under way is not undone by its result"""
    manager = await started(network, certificate)
    fridge = network["fridge"]
    loop = asyncio.get_running_loop()

    def notify_mid_read() -> None:
        network.notify("fridge", "/door/freezer/0", {"openState": "Open"})
        # Hold the read until the event loop has handled the notification.
        asyncio.run_coroutine_threadsafe(asyncio.sleep(0), loop).result(timeout=1)

    network.observation("fridge").before_read = notify_mid_read

    view = await manager.refresh("fridge")

    assert fridge.resources["/door/freezer/0"] == {"openState": "Close"}
    assert view.freezer_door_open is True


async def test_notification_before_the_first_read(network: FakeNetwork, certificate: ClientCertificate) -> None:
    """Test that a notification without a read to apply it to changes nothing"""
    manager = await started(network, certificate)
    connection = manager.appliances["fridge"].connection
    assert connection is not None
    await connection.read_resources()

    network.notify("fridge", "/door/cooler/0", {"openState": "Open"})
    await settled(manager, "fridge")

    assert not manager.view("fridge").available


async def test_failed_observation_keeps_the_read(network: FakeNetwork, certificate: ClientCertificate) -> None:
    """Test that a read whose observation fails still reports the state it read"""
    manager = await started(network, certificate)
    network.observation("fridge").error = TimeoutError("no answer")

    view = await manager.refresh("fridge")

    assert view.available and manager.appliances["fridge"].missed_reads == 0


async def test_notification_updates_the_state_at_once(network: FakeNetwork, certificate: ClientCertificate) -> None:
    """Test that a notification changes the state before its report is sent, so a later read is not overwritten"""
    manager = await started(network, certificate)
    await manager.refresh("fridge")

    network.notify("fridge", "/door/cooler/0", {"openState": "Open"})
    await asyncio.sleep(0)

    assert manager.view("fridge").fridge_door_open is True


async def test_notification_keeps_an_unavailable_appliance_unavailable(
    network: FakeNetwork, certificate: ClientCertificate
) -> None:
    """Test that a notification does not report an appliance whose reads fail as available again"""
    manager = await started(network, certificate)
    await manager.refresh("fridge")
    network["fridge"].get_reply = (0x84, None)
    for _ in range(UNAVAILABLE_AFTER):
        with pytest.raises(ApplianceUnavailable):
            await manager.refresh("fridge")

    network.notify("fridge", "/door/cooler/0", {"openState": "Open"})
    await settled(manager, "fridge")

    assert not manager.view("fridge").available
    network["fridge"].get_reply = None
    network["fridge"].resources["/door/cooler/0"] = {"openState": "Open"}
    assert (await manager.refresh("fridge")).fridge_door_open is True
