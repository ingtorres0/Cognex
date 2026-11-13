"""Mock Cognex In-Sight camera speaking Native Mode ASCII over TCP.

A real In-Sight job is usually fired with ``SE8`` (Set Event, soft trigger).
Some cells send the literal word ``Trigger``. This simulator accepts both,
waits 500 ms to imitate acquire time, then returns one comma-separated line:

    1,PASS,ON,OFF,ON,ON,OFF

The leading ``1`` is the Native Mode success code. The next field is the
inspection judgment, followed by five DIP switch positions.

``CognexCameraMock`` is the camera. ``CognexCameraClient`` is what the API uses,
so the same client can later point at a real camera by disabling the mock.
"""

from __future__ import annotations

import asyncio
import logging
import random
from dataclasses import dataclass

logger = logging.getLogger(__name__)

_TRIGGER_COMMANDS = {"SE8", "TRIGGER"}
_SWITCH_STATES = ("ON", "OFF")
_ACQUIRE_DELAY_SECONDS = 0.5
_MAX_COMMAND_BYTES = 256


class CognexError(Exception):
    """Base class for camera-link failures."""


class CognexConnectionError(CognexError):
    """The TCP session could not be opened or did not answer in time."""


class CognexProtocolError(CognexError):
    """The peer replied with a payload this service cannot use."""


@dataclass(frozen=True)
class CognexReading:
    """Parsed inspection from one trigger cycle."""

    passed: bool
    dip_positions: list[str]
    raw: str


def parse_reading(payload: str) -> CognexReading:
    """Parse ``1,PASS,ON,OFF,ON,ON,OFF`` into a structured reading."""
    raw = payload.strip()
    parts = raw.split(",")
    if len(parts) != 7:
        raise CognexProtocolError(
            f"Expected 7 comma-separated fields, received {raw!r}"
        )

    code, judgment, *positions = parts
    if code != "1":
        raise CognexProtocolError(f"Camera rejected the trigger: {raw!r}")
    if judgment not in {"PASS", "FAIL"}:
        raise CognexProtocolError(f"Unknown judgment {judgment!r} in {raw!r}")
    if any(position not in _SWITCH_STATES for position in positions):
        raise CognexProtocolError(f"Invalid DIP positions in {raw!r}")

    return CognexReading(
        passed=judgment == "PASS",
        dip_positions=positions,
        raw=raw,
    )


class CognexCameraMock:
    """Async TCP server that behaves like a single Cognex camera."""

    def __init__(self, host: str, port: int) -> None:
        self.host = host
        self.port = port
        self._server: asyncio.AbstractServer | None = None

    @property
    def is_serving(self) -> bool:
        return self._server is not None and self._server.is_serving()

    async def start(self) -> None:
        """Bind the Native Mode port. Raises ``OSError`` if the port is taken."""
        if self._server is not None:
            return
        self._server = await asyncio.start_server(
            self._handle_client,
            host=self.host,
            port=self.port,
            limit=_MAX_COMMAND_BYTES,
        )
        sockets = self._server.sockets or []
        bound = ", ".join(str(sock.getsockname()) for sock in sockets)
        logger.info("Cognex mock listening on %s", bound or f"{self.host}:{self.port}")

    async def stop(self) -> None:
        """Stop accepting connections and close the listening socket."""
        server = self._server
        self._server = None
        if server is None:
            return
        server.close()
        await server.wait_closed()
        logger.info("Cognex mock stopped")

    async def _handle_client(
        self,
        reader: asyncio.StreamReader,
        writer: asyncio.StreamWriter,
    ) -> None:
        peer = writer.get_extra_info("peername")
        try:
            while True:
                try:
                    data = await asyncio.wait_for(reader.readline(), timeout=30.0)
                except asyncio.TimeoutError:
                    logger.info("Closing idle camera session from %s", peer)
                    break
                if not data:
                    break
                if len(data) > _MAX_COMMAND_BYTES:
                    writer.write(b"0,ERR,COMMAND_TOO_LONG\r\n")
                    await writer.drain()
                    break

                command = data.decode("ascii", errors="replace").strip()
                if not command:
                    continue
                response = await self._dispatch(command)
                writer.write(response.encode("ascii"))
                await writer.drain()
        except (asyncio.IncompleteReadError, ConnectionError, OSError) as exc:
            logger.warning("Camera session from %s ended: %s", peer, exc)
        except Exception:
            logger.exception("Unexpected failure in camera session from %s", peer)
        finally:
            writer.close()
            try:
                await writer.wait_closed()
            except (ConnectionError, OSError):
                pass

    async def _dispatch(self, command: str) -> str:
        normalized = command.upper()
        if normalized in _TRIGGER_COMMANDS:
            await asyncio.sleep(_ACQUIRE_DELAY_SECONDS)
            return self._build_result()
        if normalized == "PING":
            return "1\r\n"
        logger.info("Rejected unknown camera command %r", command)
        return "0,ERR,UNKNOWN_COMMAND\r\n"

    @staticmethod
    def _build_result() -> str:
        """Build a realistic pass/fail line with five random DIP positions.

        About one in five inspections fails so the dashboard shows both states.
        The command itself still succeeds (leading ``1``).
        """
        judgment = "PASS" if random.random() >= 0.2 else "FAIL"
        positions = [random.choice(_SWITCH_STATES) for _ in range(5)]
        return ",".join(["1", judgment, *positions]) + "\r\n"


class CognexCameraClient:
    """Short-lived TCP client for trigger and health-probe commands."""

    def __init__(self, host: str, port: int, timeout: float) -> None:
        self.host = host
        self.port = port
        self.timeout = timeout

    async def trigger(self, command: str = "SE8") -> CognexReading:
        """Send a trigger and return the parsed inspection line."""
        line = await self._transact(command)
        stripped = line.strip()
        if stripped.startswith("0,"):
            raise CognexProtocolError(f"Camera returned an error: {stripped}")
        try:
            return parse_reading(stripped)
        except CognexProtocolError:
            raise
        except Exception as exc:
            raise CognexProtocolError(f"Could not parse camera response {stripped!r}") from exc

    # async def probe(self) -> bool:
    #     """Return true when the camera accepts a TCP session and answers PING."""
    #     try:
    #         reply = (await self._transact("SO1")).strip()
    #     except CognexError:
    #         return False
    #     return reply == "1"
    async def probe(self) -> bool:
        """Verifica si la camara acepta el login TCP."""
        try:
            # Mandamos un SO1 de sondeo. Si regresa 1 (Exito) o -5 (Ya estaba Online), la comunicacion funciona.
            reply = (await self._transact("SO1")).strip()
            return reply in ["1", "-5"]
        except Exception:
            return False
        
    async def _transact(self, command: str) -> str:
        try:
            reader, writer = await asyncio.wait_for(
                asyncio.open_connection(self.host, self.port),
                timeout=self.timeout,
            )
        except (OSError, asyncio.TimeoutError) as exc:
            raise CognexConnectionError(f"Camera at {self.host}:{self.port} is unreachable") from exc

        try:
            # 1. Login Cognex (Usuario admin, sin password)
            await asyncio.wait_for(reader.readuntil(b":"), timeout=self.timeout)
            writer.write(b"admin\r\n")
            await writer.drain()
            
            await asyncio.wait_for(reader.readuntil(b":"), timeout=self.timeout)
            writer.write(b"\r\n")
            await writer.drain()
            
            await asyncio.wait_for(reader.readline(), timeout=self.timeout)

            # 2. Enviar el comando exacto que pide el dashboard (ej. SE8)
            writer.write(f"{command}\r\n".encode("ascii"))
            await writer.drain()
            
            data = await asyncio.wait_for(reader.readline(), timeout=self.timeout)
            if not data:
                raise CognexProtocolError("Camera closed the connection without a response")
            return data.decode("ascii", errors="replace")
            
        finally:
            writer.close()
            try:
                await writer.wait_closed()
            except (ConnectionError, OSError):
                pass