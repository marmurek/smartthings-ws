"""The HTTP and WebSocket surface."""

import json
import logging
from contextlib import asynccontextmanager
from typing import Any, AsyncIterator, Optional

from fastapi import FastAPI, Request, Response, WebSocket, WebSocketDisconnect, status
from fastapi.responses import JSONResponse
from pydantic import ValidationError
from smartthings_local.protocol.dtls_session import DtlsCoapSession

from smartthings_ws import VERSION, auth as auth_module
from smartthings_ws.certificate import ClientCertificate
from smartthings_ws.config import Settings
from smartthings_ws.connection import SessionFactory
from smartthings_ws.errors import (
    ApplianceError,
    ApplianceNotFound,
    ApplianceUnavailable,
    CommandRejected,
    InvalidCommand,
)
from smartthings_ws.manager import ApplianceManager
from smartthings_ws.models import ApplianceUpdate, ApplianceView, RootResponse

logger = logging.getLogger(__name__)

# How the appliance layer's failures read over HTTP.
STATUS_FOR_ERROR: dict[type[Exception], int] = {
    ApplianceNotFound: status.HTTP_404_NOT_FOUND,
    InvalidCommand: status.HTTP_422_UNPROCESSABLE_ENTITY,
    CommandRejected: status.HTTP_409_CONFLICT,
    ApplianceUnavailable: status.HTTP_503_SERVICE_UNAVAILABLE,
}


def create_app(
    settings: Settings,
    session_factory: SessionFactory = DtlsCoapSession,
    certificate: Optional[ClientCertificate] = None,
) -> FastAPI:
    """Build the application around a manager configured from `settings`.

    `session_factory` and `certificate` replace the DTLS session and the
    certificate minted at startup.
    """
    manager = ApplianceManager(settings, session_factory, certificate)

    @asynccontextmanager
    async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
        """Start polling on startup and stop it on shutdown"""
        logger.info("Starting SmartThings Local API...")
        await manager.start()
        yield
        logger.info("Shutting down SmartThings Local API...")
        await manager.stop()

    app = FastAPI(
        title="SmartThings Local API",
        description="REST and WebSocket API for Samsung SmartThings appliances on the local network",
        version=VERSION,
        lifespan=lifespan,
    )
    app.state.manager = manager
    auth_module.install(app, settings.auth)

    @app.exception_handler(ApplianceError)
    async def appliance_error_handler(_request: Request, exc: Exception) -> JSONResponse:
        """Report an appliance failure with the status code that fits it"""
        code = STATUS_FOR_ERROR.get(type(exc), status.HTTP_500_INTERNAL_SERVER_ERROR)
        return JSONResponse(status_code=code, content={"detail": str(exc)})

    @app.get("/health", summary="Health probe", description="Always reachable, even when authorisation is enabled.")
    async def health() -> dict[str, str]:
        """Report that the service is up"""
        return {"status": "ok"}

    @app.get("/", summary="API info", description="API info and the names of the configured appliances.")
    async def root() -> RootResponse:
        """API info and the appliance names"""
        return RootResponse(app=app.title, version=app.version, appliances=list(manager.views))

    @app.get("/appliances", summary="List appliances", description="Every configured appliance with its state.")
    async def list_appliances() -> list[ApplianceView]:
        """Every appliance's last known state"""
        return list(manager.views.values())

    @app.get(
        "/appliances/{name}",
        summary="Get appliance",
        description="The last known state of one appliance.",
        responses={404: {"description": "No such appliance."}},
    )
    async def get_appliance(name: str) -> ApplianceView:
        """One appliance's last known state"""
        return manager.view(name)

    @app.patch(
        "/appliances/{name}",
        response_class=Response,
        status_code=status.HTTP_204_NO_CONTENT,
        responses={
            204: {"description": "The appliance accepted the command."},
            304: {"description": "The appliance already is in the requested state."},
            404: {"description": "No such appliance."},
            409: {"description": "The appliance refused the command, typically with Remote Control disabled."},
            422: {"description": "The appliance does not support the command."},
            503: {"description": "The appliance did not answer."},
        },
        summary="Send command",
        description="Only the fields present in the body are sent to the appliance.",
    )
    async def send_command(name: str, data: ApplianceUpdate) -> Response:
        """Send a command to an appliance"""
        if not await manager.send_update(name, data):
            return Response(status_code=status.HTTP_304_NOT_MODIFIED)
        return Response(status_code=status.HTTP_204_NO_CONTENT)

    @app.websocket("/ws")
    async def websocket_endpoint(websocket: WebSocket) -> None:
        """State reports and commands over one connection"""
        if not auth_module.is_valid(settings.auth, auth_module.websocket_token(websocket)):
            await websocket.close(code=auth_module.WS_POLICY_VIOLATION, reason="Missing or invalid token")
            return

        await manager.connection_manager.connect(websocket)
        try:
            await _send_ws(websocket, type="list", data=[v.model_dump(mode="json") for v in manager.views.values()])
            while True:
                await _handle_ws_message(websocket, manager)
        except WebSocketDisconnect:
            logger.info("WebSocket client disconnected")
        finally:
            manager.connection_manager.disconnect(websocket)

    return app


async def _send_ws(websocket: WebSocket, **payload: Any) -> None:
    """Send one JSON message to a client"""
    await websocket.send_text(json.dumps(payload))


async def _handle_ws_message(websocket: WebSocket, manager: ApplianceManager) -> None:
    """Read one client message and act on it"""
    try:
        message = json.loads(await websocket.receive_text())
    except json.JSONDecodeError:
        await _send_ws(websocket, type="error", message="Invalid JSON format")
        return

    if not isinstance(message, dict):
        await _send_ws(websocket, type="error", message="A message must be a JSON object")
        return

    message_id = message.get("message_id")
    if message.get("type") != "update":
        await _send_ws(
            websocket, type="error", message_id=message_id, message=f"Unsupported message type: {message.get('type')}"
        )
        return

    name = message.get("name")
    try:
        if not isinstance(name, str):
            raise ApplianceNotFound("Missing appliance name")
        changed = await manager.send_update(name, ApplianceUpdate.model_validate(message.get("data", {})))
    except (ApplianceError, ValidationError) as e:
        await _send_ws(websocket, type="error", name=name, message_id=message_id, message=str(e))
        return

    if changed:
        await _send_ws(websocket, type="applied", name=name, message_id=message_id, message="Command accepted")
    else:
        await _send_ws(
            websocket, type="not_changed", name=name, message_id=message_id, message="Already in the requested state"
        )
