"""JSON and self-contained HTML report generation."""

from __future__ import annotations

import html
import json
from pathlib import Path
from typing import Any


def write_json_report(report: dict[str, Any], output_dir: str | Path, filename: str = "report.json") -> Path:
    """Write the structured JSON report and return its path."""

    output_path = _ensure_output_dir(output_dir) / filename
    output_path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return output_path


def write_html_report(report: dict[str, Any], output_dir: str | Path, filename: str = "report.html") -> Path:
    """Write the self-contained HTML report and return its path."""

    output_path = _ensure_output_dir(output_dir) / filename
    output_path.write_text(generate_html_report(report), encoding="utf-8")
    return output_path


def generate_html_report(report: dict[str, Any]) -> str:
    """Render a complete HTML document for the telemetry report."""

    summary = report["summary"]
    channel_rows = "\n".join(_render_channel_row(channel, stats) for channel, stats in report["channels"].items())
    anomaly_rows = "\n".join(_render_anomaly_row(anomaly) for anomaly in report["anomalies"])
    if not anomaly_rows:
        anomaly_rows = '<tr><td colspan="7" class="empty">No anomalies detected</td></tr>'

    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Vehicle ECU Telemetry Test Report</title>
  <style>
    :root {{
      color-scheme: light;
      --ink: #172026;
      --muted: #5a6670;
      --line: #d8dee4;
      --panel: #f6f8fa;
      --accent: #0f766e;
      --warning: #a16207;
      --critical: #b42318;
    }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      color: var(--ink);
      background: #ffffff;
      font: 14px/1.5 -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
    }}
    main {{ max-width: 1120px; margin: 0 auto; padding: 32px 20px 48px; }}
    h1 {{ margin: 0 0 8px; font-size: 30px; }}
    h2 {{ margin: 32px 0 12px; font-size: 20px; }}
    p {{ margin: 0; color: var(--muted); }}
    .summary {{
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(150px, 1fr));
      gap: 12px;
      margin-top: 24px;
    }}
    .metric {{ border: 1px solid var(--line); border-radius: 8px; padding: 14px; background: var(--panel); }}
    .metric strong {{ display: block; font-size: 24px; color: var(--accent); }}
    .metric span {{ color: var(--muted); }}
    table {{ width: 100%; border-collapse: collapse; border: 1px solid var(--line); }}
    th, td {{ padding: 10px 12px; border-bottom: 1px solid var(--line); text-align: left; vertical-align: top; }}
    th {{ background: var(--panel); font-size: 12px; text-transform: uppercase; color: var(--muted); }}
    tr:last-child td {{ border-bottom: 0; }}
    .number {{ text-align: right; font-variant-numeric: tabular-nums; }}
    .severity {{ font-weight: 700; text-transform: uppercase; }}
    .warning {{ color: var(--warning); }}
    .critical {{ color: var(--critical); }}
    .empty {{ color: var(--muted); text-align: center; }}
  </style>
</head>
<body>
  <main>
    <h1>Vehicle ECU Telemetry Test Report</h1>
    <p>Automated threshold validation and statistical summary for simulated ECU channel readings.</p>

    <section class="summary" aria-label="Summary">
      {_metric("Total Readings", summary["total_readings"])}
      {_metric("Anomalies", summary["total_anomalies"])}
      {_metric("Warnings", summary["warning_count"])}
      {_metric("Critical", summary["critical_count"])}
      {_metric("Channels", summary["channels_analyzed"])}
    </section>

    <h2>Per-Channel Statistics</h2>
    <table>
      <thead>
        <tr>
          <th>Channel</th>
          <th class="number">Count</th>
          <th class="number">Mean</th>
          <th class="number">Std Dev</th>
          <th class="number">Min</th>
          <th class="number">Max</th>
          <th>Unit</th>
          <th class="number">Out of Range</th>
        </tr>
      </thead>
      <tbody>
        {channel_rows}
      </tbody>
    </table>

    <h2>Flagged Anomalies</h2>
    <table>
      <thead>
        <tr>
          <th>Timestamp (ms)</th>
          <th>Channel</th>
          <th class="number">Value</th>
          <th>Unit</th>
          <th>Threshold</th>
          <th>Severity</th>
          <th>Description</th>
        </tr>
      </thead>
      <tbody>
        {anomaly_rows}
      </tbody>
    </table>
  </main>
</body>
</html>
"""


def _ensure_output_dir(output_dir: str | Path) -> Path:
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)
    return output_path


def _metric(label: str, value: int | float) -> str:
    return f'<div class="metric"><strong>{html.escape(str(value))}</strong><span>{html.escape(label)}</span></div>'


def _render_channel_row(channel: str, stats: dict[str, Any]) -> str:
    return f"""<tr>
  <td>{html.escape(channel)}</td>
  <td class="number">{stats["count"]}</td>
  <td class="number">{_format_number(stats["mean"])}</td>
  <td class="number">{_format_number(stats["std_dev"])}</td>
  <td class="number">{_format_number(stats["min"])}</td>
  <td class="number">{_format_number(stats["max"])}</td>
  <td>{html.escape(stats["unit"])}</td>
  <td class="number">{_format_number(stats["percent_out_of_range"])}%</td>
</tr>"""


def _render_anomaly_row(anomaly: dict[str, Any]) -> str:
    severity = html.escape(anomaly["severity"])
    return f"""<tr>
  <td>{anomaly["timestamp_ms"]}</td>
  <td>{html.escape(anomaly["channel"])}</td>
  <td class="number">{_format_number(anomaly["value"])}</td>
  <td>{html.escape(anomaly["unit"])}</td>
  <td>{html.escape(anomaly["threshold_breached"])}</td>
  <td class="severity {severity}">{severity}</td>
  <td>{html.escape(anomaly["description"])}</td>
</tr>"""


def _format_number(value: int | float) -> str:
    return f"{float(value):.2f}"
