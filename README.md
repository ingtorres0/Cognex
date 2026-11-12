# Automated Visual Inspection

Web dashboard for a visual inspection cell. A FastAPI service triggers a Cognex-style camera over TCP, stores each reading in PostgreSQL, and pushes the result to a React dashboard over a WebSocket.

```
Browser  -- REST + WebSocket -->  FastAPI  -- SQL -->  PostgreSQL
                                  |
                                  +-- TCP Native Mode ASCII -->  Cognex mock
```

The camera in this repo is a simulator. It listens for `SE8` or `Trigger`, waits 500 ms, and answers with a line such as `1,PASS,ON,OFF,ON,ON,OFF`. Set `COGNEX_MOCK_ENABLED=false` when you are ready to point `COGNEX_HOST` / `COGNEX_PORT` at a real camera that speaks the same ASCII contract.

This stack has no authentication. Keep it on a trusted network.

## Layout

| Path | Role |
| --- | --- |
| `docker-compose.yml` | Local PostgreSQL 16 |
| `backend/main.py` | REST routes, WebSocket fan-out, process lifespan |
| `backend/database.py` | Async SQLAlchemy engine and sessions |
| `backend/models.py` | `test_results` table |
| `backend/cognex_service.py` | TCP camera mock and client |
| `backend/schemas.py` | Request and response models |
| `frontend/src/App.tsx` | Dashboard shell |
| `frontend/src/components/Dashboard.tsx` | Trigger, live status, results table |

`test_results` columns: `id`, `serial_number`, `dip_switch_status` (JSONB), `inspection_result` (boolean), `timestamp`.

## Prerequisites

- Docker Desktop
- Python 3.11+
- Node.js 20+

## 1. Start PostgreSQL

From the repository root:

```powershell
docker compose up -d
```

The database is `avi`, user `avi`, password `avi_dev_password`, on `localhost:5432`. Those values match the backend defaults. Copy `.env.example` to `backend/.env` only if you need to change them.

Tables are created on API startup. You do not need to run a migration for this boilerplate.

## 2. Start the API

```powershell
cd backend
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
uvicorn main:app --reload --host 127.0.0.1 --port 8000
```

- API docs: http://127.0.0.1:8000/docs
- Health: http://127.0.0.1:8000/api/health
- History: `GET /api/results?limit=50`
- Trigger: `POST /api/inspections` with `{"serial_number": "UNIT-1001"}` or `{}`
- Live feed: `ws://127.0.0.1:8000/ws`

The API process also binds the camera mock on `0.0.0.0:5005`. If that port is already taken, the process still starts and the dashboard shows the camera as disconnected.

A database or camera outage does not crash the process. `/api/health` and the WebSocket report `connected` or `disconnected`, and a trigger returns HTTP 503 until both links are up.

## 3. Start the dashboard

In a second terminal, from the repository root:

```powershell
cd frontend
npm install
npm run dev
```

Open http://localhost:5173. The Vite dev server proxies `/api` and `/ws` to the API, so the browser stays on port 5173.

The header shows camera, database, and WebSocket state. **Trigger Inspection** sends a soft trigger, then the new row appears in the table from the HTTP response and from the WebSocket (other open dashboards update from the socket alone).

## Camera contract

| Command | Behavior |
| --- | --- |
| `SE8` or `Trigger` | Wait 500 ms, then return `1,<PASS\|FAIL>,<ON\|OFF>` × 5 |
| `PING` | Return `1` (used by the health monitor) |
| anything else | Return `0,ERR,UNKNOWN_COMMAND` |

Commands are ASCII and terminated with LF or CRLF. About one in five simulated inspections fails so both badges show up in the table.

## Configuration

| Variable | Default |
| --- | --- |
| `DATABASE_URL` | `postgresql+asyncpg://avi:avi_dev_password@localhost:5432/avi` |
| `COGNEX_HOST` | `127.0.0.1` |
| `COGNEX_PORT` | `5005` |
| `COGNEX_BIND_HOST` | `0.0.0.0` |
| `COGNEX_TRIGGER_COMMAND` | `SE8` |
| `COGNEX_COMMAND_TIMEOUT` | `3.0` |
| `COGNEX_MOCK_ENABLED` | `true` |
| `CORS_ORIGINS` | `http://localhost:5173,http://127.0.0.1:5173` |

## Stop

```powershell
# in the API and Vite terminals: Ctrl+C
docker compose down
```

`docker compose down -v` also deletes the Postgres volume and the stored inspections.
