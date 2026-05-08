"""Live ECU telemetry dashboard served with Python stdlib and SSE."""

from __future__ import annotations

import argparse
import json
import math
import random
import sys
import threading
import time
import webbrowser
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

from analyzer import TelemetryReading, ThresholdConfig, analyze_telemetry, load_threshold_config
from reporter import generate_html_report


CHANNEL_UNITS = {
    "engine_temp_c": "C",
    "battery_voltage_v": "V",
    "vehicle_speed_kph": "kph",
    "oil_pressure_kpa": "kPa",
}


CHANNEL_BASELINES = {
    "engine_temp_c": {"mean": 91.0, "amplitude": 5.0, "noise": 1.8},
    "battery_voltage_v": {"mean": 12.8, "amplitude": 0.35, "noise": 0.1},
    "vehicle_speed_kph": {"mean": 78.0, "amplitude": 24.0, "noise": 5.0},
    "oil_pressure_kpa": {"mean": 315.0, "amplitude": 46.0, "noise": 14.0},
}


class DashboardHTTPServer(ThreadingHTTPServer):
    """HTTP server that treats dropped SSE clients as normal disconnects."""

    def handle_error(self, request: Any, client_address: Any) -> None:
        exception = sys.exception()
        if isinstance(exception, (BrokenPipeError, ConnectionResetError, OSError)):
            return
        super().handle_error(request, client_address)


def load_dashboard_config(path: str | Path) -> ThresholdConfig:
    return load_threshold_config(path)


class DashboardTelemetrySimulator:
    """Deterministic synthetic ECU stream for a live monitoring dashboard."""

    def __init__(self, thresholds: ThresholdConfig, seed: int | None = None, interval_ms: int = 250) -> None:
        self.thresholds = thresholds
        self.interval_ms = interval_ms
        self.rng = random.Random(seed)
        self.sample_index = 0
        self.channels = list(thresholds)

    def next_event(self) -> dict[str, Any]:
        channel = self.channels[self.sample_index % len(self.channels)]
        timestamp_ms = self.sample_index * self.interval_ms
        value = self._next_value(channel)
        rounded_value = round(value, 2)
        reading = TelemetryReading(timestamp_ms, channel, rounded_value, CHANNEL_UNITS.get(channel, ""))
        report = analyze_telemetry([reading], self.thresholds)
        anomaly = report["anomalies"][0] if report["anomalies"] else None
        self.sample_index += 1

        return {
            "type": "reading",
            "timestamp_ms": timestamp_ms,
            "channel": channel,
            "value": rounded_value,
            "unit": reading.unit,
            "severity": anomaly["severity"] if anomaly else "normal",
            "description": anomaly["description"] if anomaly else "Within expected operating envelope.",
            "threshold_breached": anomaly["threshold_breached"] if anomaly else "",
            "limits": self.thresholds[channel],
        }

    def _next_value(self, channel: str) -> float:
        profile = CHANNEL_BASELINES.get(channel, {"mean": 50.0, "amplitude": 8.0, "noise": 1.5})
        phase = self.sample_index / 13.0
        value = (
            profile["mean"]
            + math.sin(phase) * profile["amplitude"]
            + math.sin(phase / 3.0) * profile["amplitude"] * 0.35
            + self.rng.gauss(0.0, profile["noise"])
        )

        # Inject controlled excursions often enough to keep interviews visually interesting.
        roll = self.rng.random()
        warning = self.thresholds[channel]["warning"]
        critical = self.thresholds[channel]["critical"]
        if roll < 0.035:
            value = critical["max"] + abs(self.rng.gauss(profile["noise"] * 2.0, profile["noise"]))
        elif roll < 0.075:
            value = warning["max"] + abs(self.rng.gauss(profile["noise"] * 1.5, profile["noise"] / 2.0))
        elif roll < 0.105:
            value = warning["min"] - abs(self.rng.gauss(profile["noise"] * 1.5, profile["noise"] / 2.0))

        if channel == "vehicle_speed_kph":
            value = max(0.0, value)
        return value


def encode_sse(event_name: str, payload: dict[str, Any]) -> str:
    return f"event: {event_name}\ndata: {json.dumps(payload, sort_keys=True)}\n\n"


def build_export_report(readings: list[dict[str, Any]], thresholds: ThresholdConfig) -> dict[str, Any]:
    typed_readings = [
        TelemetryReading(
            timestamp_ms=int(item["timestamp_ms"]),
            channel=str(item["channel"]),
            value=float(item["value"]),
            unit=str(item["unit"]),
        )
        for item in readings
    ]
    return analyze_telemetry(typed_readings, thresholds)


def create_handler(thresholds: ThresholdConfig, seed: int | None, interval_ms: int) -> type[BaseHTTPRequestHandler]:
    simulator_lock = threading.Lock()
    simulator = DashboardTelemetrySimulator(thresholds, seed=seed, interval_ms=interval_ms)

    class DashboardHandler(BaseHTTPRequestHandler):
        server_version = "VehicleTelemetryDashboard/1.0"

        def do_GET(self) -> None:
            parsed = urlparse(self.path)
            if parsed.path == "/":
                self._send_text(DASHBOARD_HTML, "text/html; charset=utf-8")
            elif parsed.path == "/styles.css":
                self._send_text(DASHBOARD_CSS, "text/css; charset=utf-8")
            elif parsed.path == "/app.js":
                self._send_text(DASHBOARD_JS, "application/javascript; charset=utf-8")
            elif parsed.path == "/favicon.ico":
                self._send_text(FAVICON_SVG, "image/svg+xml; charset=utf-8")
            elif parsed.path == "/thresholds":
                self._send_json({"channels": thresholds})
            elif parsed.path == "/stream":
                query = parse_qs(parsed.query)
                limit = int(query.get("limit", ["0"])[0])
                self._stream_events(limit)
            else:
                self.send_error(HTTPStatus.NOT_FOUND, "Not found")

        def do_POST(self) -> None:
            parsed = urlparse(self.path)
            if parsed.path != "/export":
                self.send_error(HTTPStatus.NOT_FOUND, "Not found")
                return

            body_length = int(self.headers.get("Content-Length", "0"))
            payload = json.loads(self.rfile.read(body_length) or b"{}")
            report = build_export_report(payload.get("readings", []), thresholds)
            if payload.get("format") == "html":
                self._send_text(generate_html_report(report), "text/html; charset=utf-8")
            else:
                self._send_json(report)

        def log_message(self, format: str, *args: Any) -> None:
            if getattr(self.server, "quiet", False):
                return
            super().log_message(format, *args)

        def _stream_events(self, limit: int) -> None:
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Cache-Control", "no-cache")
            self.send_header("Connection", "keep-alive")
            self.end_headers()

            sent = 0
            while limit == 0 or sent < limit:
                with simulator_lock:
                    payload = simulator.next_event()
                try:
                    self.wfile.write(encode_sse("reading", payload).encode("utf-8"))
                    self.wfile.flush()
                except (BrokenPipeError, ConnectionResetError, OSError):
                    break
                sent += 1
                time.sleep(interval_ms / 1000.0)

        def _send_json(self, payload: dict[str, Any]) -> None:
            body = json.dumps(payload, indent=2, sort_keys=True).encode("utf-8")
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _send_text(self, payload: str, content_type: str) -> None:
            body = payload.encode("utf-8")
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    return DashboardHandler


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run a live ECU telemetry monitoring dashboard.")
    parser.add_argument("--config", default="config/thresholds.json", help="Threshold config JSON path.")
    parser.add_argument("--host", default="127.0.0.1", help="Host interface for the dashboard server.")
    parser.add_argument("--port", type=int, default=8765, help="Port for the dashboard server.")
    parser.add_argument("--seed", type=int, default=42, help="Random seed for repeatable streams.")
    parser.add_argument("--interval-ms", type=int, default=250, help="SSE telemetry interval in milliseconds.")
    parser.add_argument("--open", action="store_true", help="Open the dashboard in the default browser.")
    parser.add_argument("--quiet", action="store_true", help="Suppress request logs.")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    thresholds = load_dashboard_config(args.config)
    handler = create_handler(thresholds, args.seed, args.interval_ms)
    server = DashboardHTTPServer((args.host, args.port), handler)
    server.quiet = args.quiet
    url = f"http://{args.host}:{args.port}/"

    print(f"Live ECU telemetry dashboard running at {url}")
    print("Press Ctrl+C to stop.")
    if args.open:
        webbrowser.open(url)

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nDashboard stopped.")
    finally:
        server.server_close()
    return 0


DASHBOARD_HTML = """<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>ECU Live Telemetry Monitor</title>
  <link rel="stylesheet" href="/styles.css">
</head>
<body>
  <main class="dashboard-shell">
    <header class="topbar">
      <div>
        <h1>ECU Live Telemetry Monitor</h1>
        <p>Simulated real-time powertrain and chassis signal validation</p>
      </div>
      <div class="status-cluster">
        <span class="stream-dot" aria-hidden="true"></span>
        <span id="stream-status">Connecting</span>
        <button id="freeze-button" type="button">Freeze</button>
        <button id="export-json-button" type="button">Export JSON</button>
        <button id="export-html-button" type="button">Export HTML</button>
      </div>
    </header>

    <section class="overview-grid" aria-label="Live summary metrics">
      <article class="metric-panel">
        <span>Total Samples</span>
        <strong id="sample-count">0</strong>
      </article>
      <article class="metric-panel">
        <span>Warning Events</span>
        <strong id="warning-count">0</strong>
      </article>
      <article class="metric-panel critical-panel">
        <span>Critical Events</span>
        <strong id="critical-count">0</strong>
      </article>
      <article class="metric-panel">
        <span>Data Window</span>
        <strong id="window-count">0</strong>
      </article>
    </section>

    <section class="workspace">
      <section class="chart-grid" id="chart-grid" aria-label="Live channel charts"></section>
      <aside class="severity-panel" aria-label="Severity feed">
        <div class="panel-heading">
          <h2>Severity Feed</h2>
          <span id="feed-count">0 events</span>
        </div>
        <ol id="severity-feed" class="severity-feed"></ol>
      </aside>
    </section>
  </main>
  <script src="/app.js"></script>
</body>
</html>
"""


DASHBOARD_CSS = """
:root {
  --bg: #081013;
  --panel: #101a1f;
  --panel-2: #142329;
  --line: #243941;
  --text: #e6f1f2;
  --muted: #8ba1a8;
  --cyan: #28d5c4;
  --green: #74d680;
  --warning: #f8bd4a;
  --critical: #ff5c50;
  --shadow: 0 18px 50px rgba(0, 0, 0, 0.28);
}

* { box-sizing: border-box; }

body {
  margin: 0;
  min-height: 100vh;
  color: var(--text);
  background:
    radial-gradient(circle at 20% 0%, rgba(40, 213, 196, 0.12), transparent 30%),
    linear-gradient(135deg, #071012 0%, #0d171b 44%, #11181c 100%);
  font: 14px/1.45 "SF Pro Display", "Segoe UI", Arial, sans-serif;
}

button {
  border: 1px solid #35525c;
  border-radius: 6px;
  padding: 9px 12px;
  color: var(--text);
  background: #17262c;
  font: 700 12px/1 "SF Pro Display", "Segoe UI", Arial, sans-serif;
  letter-spacing: 0;
  cursor: pointer;
}

button:hover { border-color: var(--cyan); }

.dashboard-shell {
  width: min(1480px, calc(100vw - 32px));
  margin: 0 auto;
  padding: 24px 0 32px;
}

.topbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 18px;
  padding: 18px 20px;
  border: 1px solid var(--line);
  border-radius: 8px;
  background: rgba(16, 26, 31, 0.86);
  box-shadow: var(--shadow);
}

h1, h2, p { margin: 0; }
h1 { font-size: 26px; font-weight: 760; }
h2 { font-size: 16px; }
p { color: var(--muted); margin-top: 3px; }

.status-cluster {
  display: flex;
  align-items: center;
  gap: 10px;
  color: var(--muted);
  white-space: nowrap;
}

.stream-dot {
  width: 10px;
  height: 10px;
  border-radius: 50%;
  background: var(--green);
  box-shadow: 0 0 18px var(--green);
}

.stream-dot.frozen { background: var(--warning); box-shadow: 0 0 18px var(--warning); }
.stream-dot.offline { background: var(--critical); box-shadow: 0 0 18px var(--critical); }

.overview-grid {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 12px;
  margin: 14px 0;
}

.metric-panel, .chart-card, .severity-panel {
  border: 1px solid var(--line);
  border-radius: 8px;
  background: linear-gradient(180deg, rgba(20, 35, 41, 0.96), rgba(12, 21, 25, 0.96));
  box-shadow: var(--shadow);
}

.metric-panel {
  padding: 14px 16px;
}

.metric-panel span {
  display: block;
  color: var(--muted);
  font-size: 12px;
  text-transform: uppercase;
}

.metric-panel strong {
  display: block;
  margin-top: 6px;
  color: var(--cyan);
  font-size: 30px;
  line-height: 1;
  font-variant-numeric: tabular-nums;
}

.critical-panel strong { color: var(--critical); }

.workspace {
  display: grid;
  grid-template-columns: minmax(0, 1fr) 360px;
  gap: 14px;
}

.chart-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 14px;
}

.chart-card {
  min-height: 278px;
  padding: 14px;
}

.chart-header {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 12px;
  margin-bottom: 8px;
}

.chart-title {
  font-size: 14px;
  font-weight: 760;
}

.chart-value {
  color: var(--cyan);
  font-size: 24px;
  font-weight: 760;
  text-align: right;
  font-variant-numeric: tabular-nums;
}

.chart-meta {
  color: var(--muted);
  font-size: 12px;
}

.chart-card canvas {
  width: 100%;
  height: 190px;
  display: block;
  border: 1px solid rgba(80, 116, 126, 0.28);
  border-radius: 6px;
  background: #091316;
}

.severity-panel {
  min-height: 570px;
  max-height: calc(100vh - 210px);
  overflow: hidden;
  display: flex;
  flex-direction: column;
}

.panel-heading {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 14px 14px 10px;
  border-bottom: 1px solid var(--line);
}

.panel-heading span {
  color: var(--muted);
  font-size: 12px;
}

.severity-feed {
  list-style: none;
  margin: 0;
  padding: 8px;
  overflow: auto;
}

.severity-feed li {
  display: grid;
  grid-template-columns: 82px 1fr;
  gap: 10px;
  padding: 10px;
  border-bottom: 1px solid rgba(80, 116, 126, 0.25);
}

.severity-feed time {
  color: var(--muted);
  font-size: 12px;
  font-variant-numeric: tabular-nums;
}

.severity-feed strong {
  display: block;
  font-size: 13px;
}

.severity-feed p {
  margin-top: 3px;
  font-size: 12px;
}

.severity-warning strong { color: var(--warning); }
.severity-critical strong { color: var(--critical); }

@media (max-width: 1040px) {
  .topbar { align-items: flex-start; flex-direction: column; }
  .status-cluster { flex-wrap: wrap; }
  .workspace { grid-template-columns: 1fr; }
  .severity-panel { max-height: 430px; }
}

@media (max-width: 760px) {
  .dashboard-shell { width: min(100vw - 20px, 720px); padding-top: 10px; }
  .overview-grid, .chart-grid { grid-template-columns: 1fr; }
  h1 { font-size: 22px; }
}
"""


DASHBOARD_JS = """
const CHANNEL_LABELS = {
  engine_temp_c: "Engine Temperature",
  battery_voltage_v: "Battery Voltage",
  vehicle_speed_kph: "Vehicle Speed",
  oil_pressure_kpa: "Oil Pressure"
};

const MAX_POINTS = 90;
const state = {
  frozen: false,
  thresholds: {},
  readings: [],
  series: new Map(),
  warnings: 0,
  critical: 0,
  feed: []
};

const chartGrid = document.querySelector("#chart-grid");
const feedList = document.querySelector("#severity-feed");
const feedCount = document.querySelector("#feed-count");
const sampleCount = document.querySelector("#sample-count");
const warningCount = document.querySelector("#warning-count");
const criticalCount = document.querySelector("#critical-count");
const windowCount = document.querySelector("#window-count");
const statusText = document.querySelector("#stream-status");
const streamDot = document.querySelector(".stream-dot");
const freezeButton = document.querySelector("#freeze-button");

async function init() {
  const response = await fetch("/thresholds");
  const payload = await response.json();
  state.thresholds = payload.channels;
  Object.keys(state.thresholds).forEach(createChartCard);
  connectStream();
}

function createChartCard(channel) {
  state.series.set(channel, []);
  const card = document.createElement("article");
  card.className = "chart-card";
  card.dataset.channel = channel;
  card.innerHTML = `
    <div class="chart-header">
      <div>
        <div class="chart-title">${CHANNEL_LABELS[channel] || channel}</div>
        <div class="chart-meta">${channel}</div>
      </div>
      <div>
        <div class="chart-value" data-role="value">--</div>
        <div class="chart-meta" data-role="status">Awaiting stream</div>
      </div>
    </div>
    <canvas width="620" height="220" aria-label="${channel} live chart"></canvas>
  `;
  chartGrid.appendChild(card);
}

function connectStream() {
  const source = new EventSource("/stream");
  source.addEventListener("open", () => setStreamStatus("Live", "live"));
  source.addEventListener("error", () => setStreamStatus("Reconnecting", "offline"));
  source.addEventListener("reading", (event) => {
    if (state.frozen) return;
    const reading = JSON.parse(event.data);
    ingestReading(reading);
  });
}

function ingestReading(reading) {
  state.readings.push(reading);
  const points = state.series.get(reading.channel) || [];
  points.push(reading);
  if (points.length > MAX_POINTS) points.shift();
  state.series.set(reading.channel, points);

  if (reading.severity === "warning") state.warnings += 1;
  if (reading.severity === "critical") state.critical += 1;
  if (reading.severity !== "normal") addSeverityEvent(reading);

  updateMetrics();
  updateChart(reading.channel);
}

function updateMetrics() {
  sampleCount.textContent = state.readings.length.toString();
  warningCount.textContent = state.warnings.toString();
  criticalCount.textContent = state.critical.toString();
  windowCount.textContent = `${MAX_POINTS} pts`;
}

function addSeverityEvent(reading) {
  state.feed.unshift(reading);
  state.feed = state.feed.slice(0, 80);
  feedCount.textContent = `${state.feed.length} events`;
  feedList.innerHTML = state.feed.map((item) => `
    <li class="severity-${item.severity}">
      <time>${item.timestamp_ms} ms</time>
      <div>
        <strong>${item.severity.toUpperCase()} · ${CHANNEL_LABELS[item.channel] || item.channel}</strong>
        <p>${item.description}</p>
      </div>
    </li>
  `).join("");
}

function updateChart(channel) {
  const card = document.querySelector(`[data-channel="${channel}"]`);
  const points = state.series.get(channel) || [];
  const latest = points[points.length - 1];
  if (!card || !latest) return;

  card.querySelector('[data-role="value"]').textContent = `${latest.value.toFixed(2)} ${latest.unit}`;
  card.querySelector('[data-role="status"]').textContent =
    latest.severity === "normal" ? "Nominal" : latest.severity.toUpperCase();
  drawChart(card.querySelector("canvas"), points, latest.limits);
}

function drawChart(canvas, points, limits) {
  const ctx = canvas.getContext("2d");
  const width = canvas.width;
  const height = canvas.height;
  ctx.clearRect(0, 0, width, height);

  const allValues = points.map((point) => point.value);
  const low = Math.min(...allValues, limits.critical.min, limits.warning.min);
  const high = Math.max(...allValues, limits.critical.max, limits.warning.max);
  const padding = Math.max((high - low) * 0.12, 1);
  const min = low - padding;
  const max = high + padding;

  drawGrid(ctx, width, height);
  drawThreshold(ctx, width, height, limits.warning.max, min, max, "#f8bd4a");
  drawThreshold(ctx, width, height, limits.critical.max, min, max, "#ff5c50");
  drawLine(ctx, points, min, max, width, height);
}

function drawGrid(ctx, width, height) {
  ctx.strokeStyle = "rgba(139, 161, 168, 0.16)";
  ctx.lineWidth = 1;
  for (let i = 1; i < 5; i += 1) {
    const y = (height / 5) * i;
    ctx.beginPath();
    ctx.moveTo(0, y);
    ctx.lineTo(width, y);
    ctx.stroke();
  }
}

function drawThreshold(ctx, width, height, value, min, max, color) {
  const y = height - ((value - min) / (max - min)) * height;
  ctx.strokeStyle = color;
  ctx.globalAlpha = 0.65;
  ctx.setLineDash([8, 8]);
  ctx.beginPath();
  ctx.moveTo(0, y);
  ctx.lineTo(width, y);
  ctx.stroke();
  ctx.setLineDash([]);
  ctx.globalAlpha = 1;
}

function drawLine(ctx, points, min, max, width, height) {
  if (points.length < 2) return;
  ctx.strokeStyle = "#28d5c4";
  ctx.lineWidth = 3;
  ctx.beginPath();
  points.forEach((point, index) => {
    const x = (index / (MAX_POINTS - 1)) * width;
    const y = height - ((point.value - min) / (max - min)) * height;
    if (index === 0) ctx.moveTo(x, y);
    else ctx.lineTo(x, y);
  });
  ctx.stroke();

  const latest = points[points.length - 1];
  const latestX = ((points.length - 1) / (MAX_POINTS - 1)) * width;
  const latestY = height - ((latest.value - min) / (max - min)) * height;
  ctx.fillStyle = latest.severity === "critical" ? "#ff5c50" : latest.severity === "warning" ? "#f8bd4a" : "#74d680";
  ctx.beginPath();
  ctx.arc(latestX, latestY, 5, 0, Math.PI * 2);
  ctx.fill();
}

function setStreamStatus(label, mode) {
  statusText.textContent = label;
  streamDot.className = `stream-dot ${mode === "offline" ? "offline" : ""}`;
}

freezeButton.addEventListener("click", () => {
  state.frozen = !state.frozen;
  freezeButton.textContent = state.frozen ? "Resume" : "Freeze";
  statusText.textContent = state.frozen ? "Frozen" : "Live";
  streamDot.className = `stream-dot ${state.frozen ? "frozen" : ""}`;
});

document.querySelector("#export-json-button").addEventListener("click", () => exportReport("json"));
document.querySelector("#export-html-button").addEventListener("click", () => exportReport("html"));

async function exportReport(format) {
  const response = await fetch("/export", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ format, readings: state.readings })
  });
  const blob = await response.blob();
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = format === "html" ? "live-telemetry-report.html" : "live-telemetry-report.json";
  link.click();
  URL.revokeObjectURL(url);
}

init();
"""


FAVICON_SVG = """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64">
<rect width="64" height="64" rx="12" fill="#081013"/>
<path d="M12 39h9l5-18 7 30 6-20h13" fill="none" stroke="#28d5c4" stroke-width="5" stroke-linecap="round" stroke-linejoin="round"/>
</svg>"""


if __name__ == "__main__":
    raise SystemExit(main())
