"""One appliance's CoAP over DTLS connection.

smartthings-local is blocking and threaded, so every exchange runs in a worker
thread. An appliance serves one DTLS session at a time, so the exchanges of one
appliance are serialised behind a lock and the session is kept open between
them.
"""

import asyncio
import ipaddress
import logging
import zlib
from typing import Any, Callable, Optional, Protocol, Sequence

import cbor2
from smartthings_local.errors import SmartThingsLocalError
from smartthings_local.protocol.auth import CertificateAuth
from smartthings_local.protocol.dtls_session import DtlsCoapSession

from smartthings_ws.certificate import ClientCertificate
from smartthings_ws.config import ApplianceSettings
from smartthings_ws.errors import ApplianceUnavailable, CommandRejected

logger = logging.getLogger(__name__)

# The collection holding every resource of the appliance, returned with their
# representations by a single blockwise GET.
DEVICE_COLLECTION = ("device", "0")

# The appliance firmware never forgets a DTLS peer, so reconnecting from a new
# ephemeral port leaves the old context behind. A fixed source port per
# appliance makes the new handshake replace the stale context instead.
LOCAL_PORT_BASE = 61000

# Everything a failed exchange can raise: the library's own errors, socket
# errors and a malformed message.
EXCHANGE_ERRORS = (SmartThingsLocalError, OSError, TimeoutError, ValueError)

Resources = dict[str, dict[str, Any]]


class Session(Protocol):
    """The part of DtlsCoapSession this application uses"""

    def connect(self, *, timeout: Optional[float] = None) -> None:
        """Perform the DTLS handshake"""

    def start_reader(self) -> None:
        """Start the thread that receives responses and notifications"""

    def get(self, path_segs: Sequence[str], *, timeout: float = 10.0) -> tuple[int, bytes]:
        """Read one resource"""

    def post(self, path_segs: Sequence[str], body_cbor: bytes, *, timeout: float = 8.0) -> tuple[int, bytes]:
        """Update one resource"""

    def close(self) -> None:
        """Close the session and its socket"""


SessionFactory = Callable[..., Session]


def local_port(host: str) -> int:
    """The UDP source port used for one appliance, stable across restarts"""
    try:
        offset = int(ipaddress.IPv4Address(host)) & 0xFF
    except ValueError:
        offset = zlib.crc32(host.encode()) & 0xFF
    return LOCAL_PORT_BASE + offset


def coap_code(code: int) -> str:
    """A CoAP response code in its dotted notation, such as 4.04"""
    return f"{code >> 5}.{code & 0x1F:02d}"


def is_success(code: int) -> bool:
    """Is this a 2.xx response"""
    return code >> 5 == 2


def parse_collection(body: Any) -> Resources:
    """Map each href of a collection read to its representation"""
    if not isinstance(body, list):
        raise ValueError(f"expected a list of resources, got {type(body).__name__}")

    return {
        entry["href"]: entry["rep"]
        for entry in body
        if isinstance(entry, dict) and isinstance(entry.get("href"), str) and isinstance(entry.get("rep"), dict)
    }


def _describe(payload: bytes) -> str:
    """A response body as text, for an error message"""
    if not payload:
        return ""
    try:
        return str(cbor2.loads(payload))
    except cbor2.CBORDecodeError:
        return payload.decode("utf-8", errors="replace")


class ApplianceConnection:
    """The session to one appliance, reopened whenever an exchange fails"""

    def __init__(
        self,
        appliance: ApplianceSettings,
        certificate: ClientCertificate,
        timeout: float,
        session_factory: SessionFactory = DtlsCoapSession,
    ) -> None:
        self.appliance = appliance
        self._certificate = certificate
        self._timeout = timeout
        self._session_factory = session_factory
        self._session: Optional[Session] = None
        self._lock = asyncio.Lock()

    async def read_resources(self) -> Resources:
        """Read every resource of the appliance"""
        code, payload = await self._exchange(lambda s: s.get(list(DEVICE_COLLECTION), timeout=self._timeout))
        if not is_success(code):
            raise ApplianceUnavailable(f"{self.appliance.name} answered the state read with {coap_code(code)}")

        try:
            return parse_collection(cbor2.loads(payload))
        except (cbor2.CBORDecodeError, ValueError) as e:
            raise ApplianceUnavailable(f"{self.appliance.name} sent an unreadable state: {e}") from e

    async def write(self, href: str, body: dict[str, Any]) -> None:
        """Update one resource, raising CommandRejected if the appliance refuses"""
        segments = [s for s in href.split("/") if s]
        encoded = cbor2.dumps(body)
        logger.info("Writing %s %s: %s", self.appliance.name, href, body)

        code, payload = await self._exchange(lambda s: s.post(segments, encoded, timeout=self._timeout))
        if not is_success(code):
            reason = _describe(payload)
            raise CommandRejected(
                f"{self.appliance.name} refused the write to {href} with {coap_code(code)}"
                + (f": {reason}" if reason else "")
            )

    async def close(self) -> None:
        """Close the session, if one is open"""
        async with self._lock:
            await asyncio.to_thread(self._drop_session)

    async def _exchange(self, request: Callable[[Session], tuple[int, bytes]]) -> tuple[int, bytes]:
        """Run one request in a worker thread, connecting first if needed"""
        async with self._lock:
            try:
                return await asyncio.to_thread(self._request, request)
            except EXCHANGE_ERRORS as e:
                # The session state is unknown after a failure, so the next
                # exchange starts from a new handshake.
                await asyncio.to_thread(self._drop_session)
                raise ApplianceUnavailable(f"{self.appliance.name} did not answer: {type(e).__name__}: {e}") from e

    def _request(self, request: Callable[[Session], tuple[int, bytes]]) -> tuple[int, bytes]:
        """Send one request on the open session, opening it first if needed"""
        if self._session is None:
            self._session = self._connect()
        return request(self._session)

    def _connect(self) -> Session:
        """Open a session to the appliance"""
        logger.info("Connecting to %s at %s:%d", self.appliance.name, self.appliance.host, self.appliance.port)
        session = self._session_factory(
            self.appliance.host,
            self.appliance.port,
            auth=CertificateAuth.from_memory(self._certificate.certificate_pem, self._certificate.private_key_pem),
            local_port=local_port(self.appliance.host),
        )
        try:
            session.connect(timeout=self._timeout)
            session.start_reader()
        except EXCHANGE_ERRORS:
            self._close_quietly(session)
            raise
        return session

    def _drop_session(self) -> None:
        """Forget the session, closing it"""
        session, self._session = self._session, None
        if session is not None:
            self._close_quietly(session)

    @staticmethod
    def _close_quietly(session: Session) -> None:
        """Close a session whose state may be broken"""
        try:
            session.close()
        except EXCHANGE_ERRORS as e:
            logger.debug("Closing a session failed: %s", e)
