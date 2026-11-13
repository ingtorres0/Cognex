import { useCallback, useEffect, useState } from "react";
import type { LinkStatus, SocketMessage, TestResult } from "../types";

const SWITCH_LABELS = ["SW1", "SW2", "SW3", "SW4", "SW5"];

function mergeResult(current: TestResult[], incoming: TestResult): TestResult[] {
  const exists = current.some((row) => row.id === incoming.id);
  const next = exists
    ? current.map((row) => (row.id === incoming.id ? incoming : row))
    : [incoming, ...current];
  return next.sort(
    (a, b) => Date.parse(b.timestamp) - Date.parse(a.timestamp) || b.id - a.id,
  );
}

async function readError(response: Response): Promise<string> {
  try {
    const body: unknown = await response.json();
    if (body && typeof body === "object" && "detail" in body) {
      const detail = (body as { detail: unknown }).detail;
      if (typeof detail === "string") {
        return detail;
      }
      if (Array.isArray(detail)) {
        const messages = detail
          .map((item) =>
            item && typeof item === "object" && "msg" in item
              ? String((item as { msg: unknown }).msg)
              : "",
          )
          .filter(Boolean);
        if (messages.length > 0) {
          return messages.join("; ");
        }
      }
    }
  } catch {
    // The body was not JSON; fall through to the status text.
  }
  return `Request failed (${response.status})`;
}

function isSocketMessage(value: unknown): value is SocketMessage {
  return Boolean(value) && typeof value === "object" && "type" in (value as object);
}

function StatusPill({ label, status }: { label: string; status: LinkStatus }) {
  const tone =
    status === "connected"
      ? "border-emerald-500/40 bg-emerald-500/10 text-emerald-300"
      : status === "connecting"
        ? "border-amber-500/40 bg-amber-500/10 text-amber-200"
        : "border-rose-500/40 bg-rose-500/10 text-rose-300";
  const dot =
    status === "connected"
      ? "bg-emerald-400"
      : status === "connecting"
        ? "bg-amber-300"
        : "bg-rose-400";
  const text =
    status === "connected" ? "Connected" : status === "connecting" ? "Checking" : "Disconnected";

  return (
    <div className={`flex items-center justify-between rounded-lg border px-4 py-3 ${tone}`}>
      <div>
        <p className="text-xs uppercase tracking-wider text-slate-400">{label}</p>
        <p className="mt-1 text-sm font-medium">{text}</p>
      </div>
      <span className={`h-2.5 w-2.5 rounded-full ${dot}`} aria-hidden="true" />
    </div>
  );
}

function formatTime(value: string): string {
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) {
    return value;
  }
  return parsed.toLocaleString();
}

export function Dashboard() {
  const [results, setResults] = useState<TestResult[]>([]);
  const [serialNumber, setSerialNumber] = useState("");
  const [camera, setCamera] = useState<LinkStatus>("connecting");
  const [database, setDatabase] = useState<LinkStatus>("connecting");
  const [liveLink, setLiveLink] = useState<LinkStatus>("connecting");
  const [loadingHistory, setLoadingHistory] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const applyStatus = useCallback((nextCamera: LinkStatus, nextDatabase: LinkStatus) => {
    setCamera(nextCamera);
    setDatabase(nextDatabase);
  }, []);

  useEffect(() => {
    let cancelled = false;

    async function loadHistory() {
      try {
        const response = await fetch("/api/results?limit=100");
        if (!response.ok) {
          throw new Error(await readError(response));
        }
        const rows = (await response.json()) as TestResult[];
        if (!cancelled) {
          setResults(rows);
          setError(null);
        }
      } catch (err) {
        if (!cancelled) {
          setError(err instanceof Error ? err.message : "Could not load inspection history");
        }
      } finally {
        if (!cancelled) {
          setLoadingHistory(false);
        }
      }
    }

    void loadHistory();
    return () => {
      cancelled = true;
    };
  }, []);

  useEffect(() => {
    let cancelled = false;

    async function pollHealth() {
      try {
        const response = await fetch("/api/health");
        if (!response.ok) {
          throw new Error(await readError(response));
        }
        const body = (await response.json()) as {
          camera: "connected" | "disconnected";
          database: "connected" | "disconnected";
        };
        if (!cancelled) {
          applyStatus(body.camera, body.database);
        }
      } catch {
        if (!cancelled) {
          applyStatus("disconnected", "disconnected");
        }
      }
    }

    void pollHealth();
    const timer = window.setInterval(() => {
      void pollHealth();
    }, 5000);
    return () => {
      cancelled = true;
      window.clearInterval(timer);
    };
  }, [applyStatus]);

  useEffect(() => {
    let socket: WebSocket | null = null;
    let stopped = false;
    let retryMs = 500;
    let retryTimer = 0;

    const connect = () => {
      // const protocol = window.location.protocol === "https:" ? "wss" : "ws";
      // socket = new WebSocket(`${protocol}//${window.location.host}/ws`);

      // socket.onopen = () => {
      // Nos saltamos el proxy de Vite y vamos directo al backend
      socket = new WebSocket("ws://127.0.0.1:8000/ws");

      socket.onopen = () => {
        retryMs = 500;
        setLiveLink("connected");
      };

      socket.onmessage = (event: MessageEvent<string>) => {
        let payload: unknown;
        try {
          payload = JSON.parse(event.data) as unknown;
        } catch {
          return;
        }
        if (!isSocketMessage(payload)) {
          return;
        }
        if (payload.type === "status") {
          applyStatus(payload.camera, payload.database);
          return;
        }
        if (payload.type === "inspection") {
          setResults((current) => mergeResult(current, payload.result));
          setError(null);
          return;
        }
        if (payload.type === "error") {
          setError(payload.message);
        }
      };

      socket.onclose = () => {
        setLiveLink("disconnected");
        if (!stopped) {
          retryTimer = window.setTimeout(connect, retryMs);
          retryMs = Math.min(retryMs * 2, 8000);
        }
      };
    };

    connect();
    return () => {
      stopped = true;
      window.clearTimeout(retryTimer);
      socket?.close();
    };
  }, [applyStatus]);

  async function triggerInspection() {
    setBusy(true);
    setError(null);
    try {
      const response = await fetch("/api/inspections", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          serial_number: serialNumber.trim() ? serialNumber.trim() : null,
        }),
      });
      if (!response.ok) {
        throw new Error(await readError(response));
      }
      const row = (await response.json()) as TestResult;
      setResults((current) => mergeResult(current, row));
      setSerialNumber("");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Inspection failed");
    } finally {
      setBusy(false);
    }
  }

  const latest = results[0];

  return (
    <div className="space-y-6">
      <section className="grid gap-4 lg:grid-cols-[minmax(0,1.4fr)_minmax(0,1fr)]">
        <div className="rounded-xl border border-slate-800 bg-slate-900/70 p-5">
          <div className="flex items-start justify-between gap-4">
            <div>
              <h2 className="text-base font-semibold text-white">Inspection control</h2>
              <p className="mt-1 text-sm text-slate-400">
                Sends <span className="font-mono text-slate-200">SE8</span> to the camera,
                waits for the ASCII result, and stores it.
              </p>
            </div>
          </div>

          <label className="mt-5 block text-xs uppercase tracking-wider text-slate-400" htmlFor="serial">
            Serial number
          </label>
          <div className="mt-2 flex flex-col gap-3 sm:flex-row">
            <input
              id="serial"
              value={serialNumber}
              onChange={(event) => setSerialNumber(event.target.value)}
              placeholder="Leave blank to generate one"
              maxLength={64}
              autoComplete="off"
              className="w-full rounded-lg border border-slate-700 bg-slate-950 px-3 py-2 font-mono text-sm text-slate-100 outline-none ring-amber-400/40 placeholder:text-slate-600 focus:ring-2"
            />
            <button
              type="button"
              onClick={() => {
                void triggerInspection();
              }}
              disabled={busy || camera !== "connected" || database !== "connected"}
              aria-busy={busy}
              className="shrink-0 rounded-lg bg-amber-400 px-4 py-2 text-sm font-semibold text-slate-950 transition hover:bg-amber-300 disabled:cursor-not-allowed disabled:bg-slate-700 disabled:text-slate-400"
            >
              {busy ? "Inspecting…" : "Trigger Inspection"}
            </button>
          </div>
          <p className="mt-3 text-xs text-slate-500">
            The trigger stays disabled until both the camera and the database report connected.
          </p>
        </div>

        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-1">
          <StatusPill label="Camera" status={camera} />
          <StatusPill label="Database" status={database} />
          <div className="rounded-lg border border-slate-800 bg-slate-900/70 px-4 py-3 sm:col-span-2 lg:col-span-1">
            <p className="text-xs uppercase tracking-wider text-slate-400">Live feed</p>
            <p className="mt-1 text-sm text-slate-200">
              {liveLink === "connected"
                ? "WebSocket connected"
                : liveLink === "connecting"
                  ? "Opening WebSocket…"
                  : "WebSocket disconnected — retrying"}
            </p>
            <p className="mt-2 text-xs text-slate-500">
              {latest
                ? `Last result: ${latest.inspection_result ? "PASS" : "FAIL"} · ${latest.serial_number}`
                : "No inspections stored yet"}
            </p>
          </div>
        </div>
      </section>

      {error ? (
        <div
          role="alert"
          className="rounded-lg border border-rose-500/40 bg-rose-500/10 px-4 py-3 text-sm text-rose-200"
        >
          {error}
        </div>
      ) : null}

      <section className="overflow-hidden rounded-xl border border-slate-800 bg-slate-900/70">
        <div className="flex items-center justify-between border-b border-slate-800 px-5 py-4">
          <h2 className="text-base font-semibold text-white">Inspection results</h2>
          <p className="text-xs text-slate-500">{results.length} shown</p>
        </div>
        <div className="max-h-[32rem] overflow-auto">
          <table className="min-w-full text-left text-sm">
            <caption className="sr-only">Recent visual inspection results</caption>
            <thead className="sticky top-0 bg-slate-900 text-xs uppercase tracking-wider text-slate-500">
              <tr>
                <th className="px-4 py-3 font-medium">Time</th>
                <th className="px-4 py-3 font-medium">Serial</th>
                <th className="px-4 py-3 font-medium">Result</th>
                <th className="px-4 py-3 font-medium">DIP switches</th>
                <th className="hidden px-4 py-3 font-medium md:table-cell">Raw</th>
              </tr>
            </thead>
            <tbody>
              {loadingHistory ? (
                <tr>
                  <td colSpan={5} className="px-4 py-8 text-slate-400">
                    Loading history…
                  </td>
                </tr>
              ) : results.length === 0 && error ? (
                <tr>
                  <td colSpan={5} className="px-4 py-8 text-slate-400">
                    History is unavailable until the database is connected.
                  </td>
                </tr>
              ) : results.length === 0 ? (
                <tr>
                  <td colSpan={5} className="px-4 py-8 text-slate-400">
                    No inspections yet. Trigger one to begin.
                  </td>
                </tr>
              ) : (
                results.map((row) => {
                  const positions = row.dip_switch_status?.positions ?? [];
                  return (
                    <tr key={row.id} className="border-t border-slate-800/80">
                      <td className="whitespace-nowrap px-4 py-3 text-slate-300">
                        {formatTime(row.timestamp)}
                      </td>
                      <td className="whitespace-nowrap px-4 py-3 font-mono text-slate-100">
                        {row.serial_number}
                      </td>
                      <td className="px-4 py-3">
                        <span
                          className={
                            row.inspection_result
                              ? "rounded-full bg-emerald-500/15 px-2.5 py-1 text-xs font-semibold text-emerald-300"
                              : "rounded-full bg-rose-500/15 px-2.5 py-1 text-xs font-semibold text-rose-300"
                          }
                        >
                          {row.inspection_result ? "PASS" : "FAIL"}
                        </span>
                      </td>
                      <td className="px-4 py-3">
                        <div className="flex flex-wrap gap-1.5">
                          {SWITCH_LABELS.map((label, index) => {
                            const position = positions[index] ?? "—";
                            const on = position === "ON";
                            return (
                              <span
                                key={label}
                                className={
                                  on
                                    ? "rounded border border-amber-400/40 bg-amber-400/10 px-1.5 py-0.5 font-mono text-[11px] text-amber-200"
                                    : "rounded border border-slate-700 bg-slate-950 px-1.5 py-0.5 font-mono text-[11px] text-slate-400"
                                }
                              >
                                {label} {position}
                              </span>
                            );
                          })}
                        </div>
                      </td>
                      <td className="hidden whitespace-nowrap px-4 py-3 font-mono text-xs text-slate-500 md:table-cell">
                        {row.dip_switch_status?.raw ?? ""}
                      </td>
                    </tr>
                  );
                })
              )}
            </tbody>
          </table>
        </div>
      </section>
    </div>
  );
}
