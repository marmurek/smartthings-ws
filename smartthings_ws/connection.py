"""One appliance's CoAP over DTLS connection.

smartthings-local is blocking and threaded, so every exchange runs in a worker
thread. An appliance serves one DTLS session at a time, so the exchanges of one
appliance are serialised behind a lock and the session is kept open between
them.

Changes are also observed (CoAP Observe, RFC 7641): the session's reader thread
hands every notification to the callback the connection was created with.
Observe relations belong to the session, so a new session subscribes again.
"""

import asyncio
import functools
import ipaddress
import logging
import time
import zlib
from typing import Any, Callable, Iterable, Optional, Protocol, Sequence, TypeVar

import cbor2
from smartthings_local.errors import SmartThingsLocalError
from smartthings_local.protocol.auth import CertificateAuth
from smartthings_local.protocol.dtls_session import DtlsCoapSession

from smartthings_ws.certificate import ClientCertificate
from smartthings_ws.config import ApplianceSettings
from smartthings_ws.errors import ApplianceUnavailable, CommandRejected

logger = logging.getLogger(__name__)

# The collection holding every resource of the appliance, returned with their
# representations by a single blockwise GET. A dual-cavity oven serves its
# lower cavity as a second collection, `/device/1`, with resources at `/vs/1`.
DEVICE_COLLECTION = "/device/0"

# The appliance firmware never forgets a DTLS peer, so reconnecting from a new
# ephemeral port leaves the old context behind. A fixed source port per
# appliance makes the new handshake replace the stale context instead.
LOCAL_PORT_BASE = 61000

# Everything a failed exchange can raise: the library's own errors, socket
# errors and a malformed message.
EXCHANGE_ERRORS = (SmartThingsLocalError, OSError, TimeoutError, ValueError)

# The most Observe relations smartthings-local keeps on one session.
MAX_OBSERVED = 255

# The appliance firmware can stop delivering notifications on a healthy
# session, so the relations are renewed at this interval, in seconds.
OBSERVE_REFRESH = 6 * 3600.0

Resources = dict[str, dict[str, Any]]

# Called from the session's reader thread with the href and the representation
# a notification carries. The representation may hold only the changed keys.
NotificationHandler = Callable[[str, dict[str, Any]], None]

T = TypeVar("T")


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

    def subscribe(self, path_segs: Sequence[str]) -> Any:
        """Register an Observe relation on one resource"""

    def refresh_observes(self, paths: Iterable[Sequence[str]]) -> Any:
        """Replace the Observe relations of the given resources"""

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


def _segments(href: str) -> list[str]:
    """The path segments of an href"""
    return [s for s in href.split("/") if s]


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
        on_notification: Optional[NotificationHandler] = None,
    ) -> None:
        self.appliance = appliance
        self._timeout = timeout
        self._on_notification = on_notification
        self._open_session = functools.partial(
            session_factory,
            appliance.host,
            appliance.port,
            auth=CertificateAuth.from_memory(certificate.certificate_pem, certificate.private_key_pem),
            local_port=local_port(appliance.host),
            on_observe_delivery=None if on_notification is None else functools.partial(self._deliver, on_notification),
        )
        self._session: Optional[Session] = None
        # The session the Observe relations were registered on, and when.
        self._observed: Optional[tuple[Session, float]] = None
        self._lock = asyncio.Lock()

    async def read_resources(self, collection: str = DEVICE_COLLECTION) -> Resources:
        """Read every resource of a collection, by default the whole appliance"""
        segments = _segments(collection)
        code, payload = await self._run(lambda s: s.get(segments, timeout=self._timeout))
        if not is_success(code):
            raise ApplianceUnavailable(
                f"{self.appliance.name} answered the read of {collection} with {coap_code(code)}"
            )

        try:
            return parse_collection(cbor2.loads(payload))
        except (cbor2.CBORDecodeError, ValueError) as e:
            raise ApplianceUnavailable(f"{self.appliance.name} sent an unreadable state: {e}") from e

    async def write(self, href: str, body: dict[str, Any] | list[dict[str, Any]]) -> None:
        """Update one resource, raising CommandRejected if the appliance refuses"""
        segments = _segments(href)
        encoded = cbor2.dumps(body)
        logger.info("Writing %s %s: %s", self.appliance.name, href, body)

        code, payload = await self._run(lambda s: s.post(segments, encoded, timeout=self._timeout))
        if not is_success(code):
            reason = _describe(payload)
            raise CommandRejected(
                f"{self.appliance.name} refused the write to {href} with {coap_code(code)}"
                + (f": {reason}" if reason else "")
            )

    async def observe(self, hrefs: Iterable[str]) -> None:
        """Observe the resources, unless the current session already does.

        Registers the relations on a new session and renews them once they are
        OBSERVE_REFRESH old. Without a notification handler nothing is observed.
        """
        if self._on_notification is None or self._observes(self._session):
            return
        paths = [_segments(href) for href in sorted(hrefs)][:MAX_OBSERVED]
        await self._run(lambda s: self._register(s, paths))

    def _observes(self, session: Optional[Session]) -> bool:
        """Whether the session holds relations that are not due for renewal"""
        return (
            self._observed is not None
            and self._observed[0] is session
            and time.monotonic() - self._observed[1] < OBSERVE_REFRESH
        )

    def _register(self, session: Session, paths: list[list[str]]) -> None:
        """Register or renew the Observe relations on the open session"""
        # Another call may have registered the relations while the lock was awaited.
        if self._observes(session):
            return
        if self._observed is not None and self._observed[0] is session:
            logger.info("Renewing the observation of %d resources of %s", len(paths), self.appliance.name)
            session.refresh_observes(paths)
        else:
            logger.info("Observing %d resources of %s", len(paths), self.appliance.name)
            for path in paths:
                session.subscribe(path)
        self._observed = (session, time.monotonic())

    def _deliver(self, handler: NotificationHandler, delivery: Any) -> None:
        """Decode a notification and hand it to the handler, on the reader thread"""
        try:
            rep = cbor2.loads(delivery.payload)
        except cbor2.CBORDecodeError as e:
            logger.debug("%s sent an unreadable notification for %s: %s", self.appliance.name, delivery.href, e)
            return
        if isinstance(rep, dict):
            handler(delivery.href, rep)

    async def close(self) -> None:
        """Close the session, if one is open"""
        async with self._lock:
            await asyncio.to_thread(self._drop_session)

    async def _run(self, request: Callable[[Session], T]) -> T:
        """Run one request in a worker thread, connecting first if needed"""
        async with self._lock:
            try:
                return await asyncio.to_thread(self._request, request)
            except EXCHANGE_ERRORS as e:
                # The session state is unknown after a failure, so the next
                # exchange starts from a new handshake.
                await asyncio.to_thread(self._drop_session)
                raise ApplianceUnavailable(f"{self.appliance.name} did not answer: {type(e).__name__}: {e}") from e

    def _request(self, request: Callable[[Session], T]) -> T:
        """Send one request on the open session, opening it first if needed"""
        if self._session is None:
            self._session = self._connect()
        return request(self._session)

    def _connect(self) -> Session:
        """Open a session to the appliance"""
        logger.info("Connecting to %s at %s:%d", self.appliance.name, self.appliance.host, self.appliance.port)
        session = self._open_session()
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
