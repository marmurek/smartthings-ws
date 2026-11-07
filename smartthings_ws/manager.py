"""Polling the appliances, reporting changes and sending commands."""

import asyncio
import json
import logging
from dataclasses import dataclass
from typing import Any, Optional

from fastapi import WebSocket, WebSocketDisconnect
from smartthings_local.protocol.dtls_session import DtlsCoapSession

from smartthings_ws.certificate import ClientCertificate, mint_client_certificate
from smartthings_ws.commands import plan_writes
from smartthings_ws.config import Settings
from smartthings_ws.connection import ApplianceConnection, Resources, SessionFactory
from smartthings_ws.errors import ApplianceNotFound, ApplianceUnavailable
from smartthings_ws.models import ApplianceUpdate, ApplianceView
from smartthings_ws.state import read_view

logger = logging.getLogger(__name__)

# Consecutive failed reads before an appliance is reported unavailable. One
# lost exchange is common on Wi-Fi and is retried on the next poll.
UNAVAILABLE_AFTER = 3


class ConnectionManager:
    """The WebSocket clients and broadcasting to them"""

    def __init__(self) -> None:
        self.active_connections: set[WebSocket] = set()

    async def connect(self, websocket: WebSocket) -> None:
        """Accept a WebSocket connection and start tracking it"""
        await websocket.accept()
        self.active_connections.add(websocket)

    def disconnect(self, websocket: WebSocket) -> None:
        """Stop tracking a WebSocket connection"""
        self.active_connections.discard(websocket)

    @staticmethod
    async def _send_to(connection: WebSocket, payload: str) -> Optional[WebSocket]:
        """Send one payload, returning the connection if it has to be dropped"""
        try:
            await connection.send_text(payload)
        except (WebSocketDisconnect, RuntimeError, OSError):
            return connection
        return None

    async def broadcast(self, data: dict[str, Any]) -> None:
        """Send data to every connected client, dropping the ones that went away"""
        payload = json.dumps(data)

        # A snapshot, since clients may connect or leave during the sends.
        connections = list(self.active_connections)
        results = await asyncio.gather(*(self._send_to(c, payload) for c in connections))

        for connection in results:
            if connection is not None:
                self.active_connections.discard(connection)


def changes_between(old: ApplianceView, new: ApplianceView) -> dict[str, dict[str, Any]]:
    """The fields that differ between two readings, as the API reports them"""
    before, after = old.model_dump(mode="json"), new.model_dump(mode="json")
    return {name: {"old": before[name], "new": value} for name, value in after.items() if before[name] != value}


@dataclass
class TrackedAppliance:
    """What the manager holds for one appliance"""

    view: ApplianceView
    connection: Optional[ApplianceConnection] = None
    # The resources of the last successful read; commands are planned against them.
    resources: Optional[Resources] = None
    missed_reads: int = 0
    task: Optional[asyncio.Task[None]] = None
    # The read that follows a command, kept so it is not garbage collected mid-run.
    read_back: Optional[asyncio.Task[None]] = None


class ApplianceManager:
    """The configured appliances, their last known state and their polling"""

    def __init__(
        self,
        settings: Settings,
        session_factory: SessionFactory = DtlsCoapSession,
        certificate: Optional[ClientCertificate] = None,
    ) -> None:
        self.settings = settings
        self.connection_manager = ConnectionManager()
        self._session_factory = session_factory
        self._certificate = certificate
        self.appliances = {
            a.name: TrackedAppliance(ApplianceView(name=a.name, host=a.host)) for a in settings.appliances
        }

    @property
    def views(self) -> dict[str, ApplianceView]:
        """The last known state of every appliance, by name"""
        return {name: tracked.view for name, tracked in self.appliances.items()}

    async def start(self) -> None:
        """Open the connections and start polling every appliance"""
        if self._certificate is None:
            # RSA key generation takes long enough to be worth keeping off the event loop.
            self._certificate = await asyncio.to_thread(mint_client_certificate)

        for appliance in self.settings.appliances:
            tracked = self.appliances[appliance.name]
            tracked.connection = ApplianceConnection(
                appliance, self._certificate, self.settings.polling.response_timeout, self._session_factory
            )
            tracked.task = asyncio.create_task(self._poll(appliance.name))

    async def stop(self) -> None:
        """Stop polling and close every connection"""
        tasks = [task for t in self.appliances.values() for task in (t.task, t.read_back) if task is not None]
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        await asyncio.gather(*(t.connection.close() for t in self.appliances.values() if t.connection is not None))

    def _tracked(self, name: str) -> TrackedAppliance:
        """One appliance, raising ApplianceNotFound for an unknown name"""
        if name not in self.appliances:
            raise ApplianceNotFound(f"No appliance is configured as {name}")
        return self.appliances[name]

    def view(self, name: str) -> ApplianceView:
        """The last known state of one appliance"""
        return self._tracked(name).view

    @staticmethod
    def _connection(tracked: TrackedAppliance) -> ApplianceConnection:
        """The appliance's connection, which exists once the manager has started"""
        if tracked.connection is None:
            raise ApplianceUnavailable(f"{tracked.view.name} is not connected yet")
        return tracked.connection

    async def refresh(self, name: str) -> ApplianceView:
        """Read one appliance and report whatever changed"""
        tracked = self._tracked(name)
        try:
            resources = await self._connection(tracked).read_resources()
        except ApplianceUnavailable as e:
            tracked.missed_reads += 1
            if tracked.missed_reads == 1:
                logger.warning("%s", e)
            if tracked.missed_reads >= UNAVAILABLE_AFTER:
                await self._publish(tracked, tracked.view.model_copy(update={"available": False}))
            raise

        if tracked.missed_reads:
            logger.info("%s is answering again after %d failed reads", name, tracked.missed_reads)
        tracked.missed_reads = 0
        tracked.resources = resources
        await self._publish(tracked, read_view(name, tracked.view.host, resources))
        return tracked.view

    async def _publish(self, tracked: TrackedAppliance, view: ApplianceView) -> None:
        """Store a new reading and tell clients what moved"""
        changes = changes_between(tracked.view, view)
        tracked.view = view
        if not changes:
            return

        logger.debug("%s changed: %s", view.name, changes)
        await self.connection_manager.broadcast({"type": "report", "name": view.name, "data": changes})

    async def _poll(self, name: str) -> None:
        """Read one appliance at the polling interval until cancelled"""
        while True:
            try:
                await self.refresh(name)
            except ApplianceUnavailable:
                pass
            await asyncio.sleep(self.settings.polling.interval)

    async def send_update(self, name: str, update: ApplianceUpdate) -> bool:
        """Send a command, reporting whether it changed anything.

        The appliance is read again in the background once the writes are done,
        including after a failed write, since the writes before it may have been
        applied. Clients see the result as an ordinary change report.
        """
        tracked = self._tracked(name)
        if tracked.resources is None or not tracked.view.available:
            raise ApplianceUnavailable(f"The state of {name} is not known yet")

        writes = plan_writes(tracked.view, tracked.resources, update)
        if not writes:
            return False

        connection = self._connection(tracked)
        try:
            for write in writes:
                await connection.write(write.href, write.body)
        finally:
            tracked.read_back = asyncio.create_task(self._read_back(name))
        return True

    async def _read_back(self, name: str) -> None:
        """Read an appliance after a command"""
        try:
            await self.refresh(name)
        except ApplianceUnavailable:
            logger.warning("%s could not be read back after a command", name)
