"""FastAPI application for the automated visual inspection cell.

Routes
------
GET  /api/results       Historical inspections, newest first.
POST /api/inspections   Trigger the camera, store the reading, push it live.
GET  /api/health        Current camera and database link state.
WS   /ws                Status snapshots and newly stored inspections.

The process owns the Cognex TCP mock unless ``COGNEX_MOCK_ENABLED`` is false.
Database and camera outages are reported as disconnected; they do not take
the API process down.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import secrets
from datetime import datetime, timezone

from fastapi import Body, Depends, FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from cognex_service import (
    CognexCameraClient,
    CognexCameraMock,
    CognexConnectionError,
    CognexError,
    CognexProtocolError,
)
from config import settings
from database import dispose_engine, ensure_schema, get_db, ping_database
from models import TestResult
from schemas import HealthStatus, InspectionRequest, ServiceInfo, TestResultRead

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger("avi")


class RuntimeState:
    """Links the lifespan task, the camera client, and the route handlers."""

    def __init__(self) -> None:
        self.db_ready = False
        self.camera_ready = False
        self.cognex = CognexCameraClient(
            host=settings.cognex_host,
            port=settings.cognex_port,
            timeout=settings.cognex_command_timeout,
        )
        self.mock: CognexCameraMock | None = None


class ConnectionManager:
    """Fan-out helper for dashboard WebSocket clients."""

    def __init__(self) -> None:
        self._connections: set[WebSocket] = set()
        self._lock = asyncio.Lock()

    async def connect(self, websocket: WebSocket) -> None:
        await websocket.accept()
        async with self._lock:
            self._connections.add(websocket)

    async def disconnect(self, websocket: WebSocket) -> None:
        async with self._lock:
            self._connections.discard(websocket)

    async def broadcast(self, message: dict) -> None:
        async with self._lock:
            targets = list(self._connections)
        stale: list[WebSocket] = []
        for websocket in targets:
            try:
                await websocket.send_json(message)
            except Exception:
                stale.append(websocket)
        for websocket in stale:
            await self.disconnect(websocket)


runtime = RuntimeState()
manager = ConnectionManager()


def _link_label(ready: bool) -> str:
    return "connected" if ready else "disconnected"


def status_message() -> dict:
    return {
        "type": "status",
        "camera": _link_label(runtime.camera_ready),
        "database": _link_label(runtime.db_ready),
    }


def _new_serial() -> str:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    return f"SN-{stamp}-{secrets.token_hex(2).upper()}"


async def _supervise(initial_ready: asyncio.Event) -> None:
    """Keep schema, health flags, and live status in sync with the plant.

    ``initial_ready`` is set after the first sweep so the API does not answer
    health checks before it has tried the database and the camera once.
    """
    schema_ready = False
    last_db: bool | None = None
    last_camera: bool | None = None
    announced_start = False

    while True:
        if not schema_ready:
            schema_ready, schema_error = await ensure_schema()
            if not schema_ready and last_db is not False:
                logger.warning("Database schema is unavailable: %s", schema_error)

        if schema_ready:
            db_ready, db_error = await ping_database()
        else:
            db_ready, db_error = False, "schema is not initialized"

        camera_ready = await runtime.cognex.probe()
        runtime.db_ready = db_ready
        runtime.camera_ready = camera_ready

        if db_ready != last_db:
            if db_ready:
                logger.info("Database connected")
            else:
                logger.warning("Database disconnected: %s", db_error)
            last_db = db_ready
        if camera_ready != last_camera:
            logger.info(
                "Camera %s (%s:%s)",
                _link_label(camera_ready),
                settings.cognex_host,
                settings.cognex_port,
            )
            last_camera = camera_ready

        await manager.broadcast(status_message())
        if not announced_start:
            initial_ready.set()
            announced_start = True
        await asyncio.sleep(2)


@contextlib.asynccontextmanager
async def lifespan(app: FastAPI):
    """Start the camera mock and the health monitor; stop both on shutdown."""
    if settings.cognex_mock_enabled:
        mock = CognexCameraMock(
            host=settings.cognex_bind_host,
            port=settings.cognex_port,
        )
        try:
            await mock.start()
        except OSError as exc:
            logger.error(
                "Could not bind the Cognex mock on %s:%s (%s). "
                "Camera status will stay disconnected.",
                settings.cognex_bind_host,
                settings.cognex_port,
                exc,
            )
        else:
            runtime.mock = mock

    initial_ready = asyncio.Event()
    monitor = asyncio.create_task(_supervise(initial_ready), name="avi-supervisor")
    try:
        try:
            await asyncio.wait_for(initial_ready.wait(), timeout=15)
        except asyncio.TimeoutError:
            logger.warning("Initial camera/database sweep did not finish within 15s")
        yield
    finally:
        monitor.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await monitor
        if runtime.mock is not None:
            await runtime.mock.stop()
            runtime.mock = None
        await dispose_engine()


app = FastAPI(
    title="Automated Visual Inspection",
    summary="Inspection records, a Cognex Native Mode mock, and a live dashboard feed.",
    version="0.1.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/", response_model=ServiceInfo)
async def root() -> ServiceInfo:
    return ServiceInfo(
        service="AVI inspection API",
        docs="/docs",
        health="/api/health",
    )


@app.get("/api/health", response_model=HealthStatus)
async def health() -> HealthStatus:
    return HealthStatus(
        camera=_link_label(runtime.camera_ready),
        database=_link_label(runtime.db_ready),
    )


@app.get("/api/results", response_model=list[TestResultRead])
async def list_results(
    limit: int = 50,
    session: AsyncSession = Depends(get_db),
) -> list[TestResult]:
    """Return the newest stored inspections."""
    if limit < 1 or limit > 500:
        raise HTTPException(status_code=422, detail="limit must be between 1 and 500")
    if not runtime.db_ready:
        raise HTTPException(status_code=503, detail="Database is disconnected")

    try:
        statement = (
            select(TestResult).order_by(TestResult.timestamp.desc(), TestResult.id.desc()).limit(limit)
        )
        rows = await session.execute(statement)
        return list(rows.scalars().all())
    except Exception as exc:
        logger.exception("Failed to read inspection history")
        raise HTTPException(status_code=503, detail="Database query failed") from exc


@app.post("/api/inspections", response_model=TestResultRead, status_code=201)
async def trigger_inspection(
    body: InspectionRequest | None = Body(default=None),
    session: AsyncSession = Depends(get_db),
) -> TestResult:
    """Fire the camera, persist the reading, and broadcast it to dashboards."""
    if not runtime.camera_ready:
        raise HTTPException(status_code=503, detail="Camera is disconnected")
    if not runtime.db_ready:
        raise HTTPException(status_code=503, detail="Database is disconnected")

    serial_number = body.serial_number if body and body.serial_number else _new_serial()

    try:
        reading = await runtime.cognex.trigger(settings.cognex_trigger_command)
    except CognexConnectionError as exc:
        runtime.camera_ready = False
        await manager.broadcast(status_message())
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except CognexProtocolError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    except CognexError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    record = TestResult(
        serial_number=serial_number,
        dip_switch_status={"positions": reading.dip_positions, "raw": reading.raw},
        inspection_result=reading.passed,
    )
    session.add(record)
    try:
        await session.commit()
        await session.refresh(record)
    except Exception as exc:
        logger.exception("Failed to store inspection for %s", serial_number)
        runtime.db_ready = False
        await manager.broadcast(status_message())
        raise HTTPException(status_code=503, detail="Could not store the inspection") from exc

    payload = TestResultRead.model_validate(record).model_dump(mode="json")
    await manager.broadcast({"type": "inspection", "result": payload})
    logger.info(
        "Inspection %s serial=%s result=%s",
        record.id,
        record.serial_number,
        "PASS" if record.inspection_result else "FAIL",
    )
    return record


@app.websocket("/ws")
async def inspection_socket(websocket: WebSocket) -> None:
    """Push link status and new inspections. Client text is ignored except ping."""
    await manager.connect(websocket)
    try:
        await websocket.send_json(status_message())
        while True:
            try:
                incoming = await asyncio.wait_for(websocket.receive_text(), timeout=30.0)
            except asyncio.TimeoutError:
                continue
            if incoming.strip().lower() == "ping":
                await websocket.send_json({"type": "pong"})
    except WebSocketDisconnect:
        pass
    except Exception:
        logger.debug("WebSocket client closed", exc_info=True)
    finally:
        await manager.disconnect(websocket)
