"""Telemetry parsing, threshold evaluation, and report aggregation."""

from __future__ import annotations

import csv
import json
import statistics
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any


REQUIRED_COLUMNS = {"timestamp_ms", "channel", "value", "unit"}
SEVERITIES = ("critical", "warning")
BOUNDS = ("min", "max")


@dataclass(frozen=True)
class TelemetryReading:
    """One ECU telemetry sample from the input CSV."""

    timestamp_ms: int
    channel: str
    value: float
    unit: str


ThresholdConfig = dict[str, dict[str, dict[str, float]]]


def parse_telemetry_csv(path: str | Path) -> list[TelemetryReading]:
    """Parse a telemetry CSV and convert rows into typed readings."""

    csv_path = Path(path)
    readings: list[TelemetryReading] = []

    with csv_path.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        fieldnames = set(reader.fieldnames or [])
        missing = REQUIRED_COLUMNS - fieldnames
        if missing:
            names = ", ".join(sorted(missing))
            raise ValueError(f"{csv_path} missing required columns: {names}")

        for line_number, row in enumerate(reader, start=2):
            try:
                readings.append(
                    TelemetryReading(
                        timestamp_ms=int(_require_cell(row, "timestamp_ms")),
                        channel=_require_cell(row, "channel"),
                        value=float(_require_cell(row, "value")),
                        unit=_require_cell(row, "unit"),
                    )
                )
            except ValueError as exc:
                raise ValueError(f"{csv_path}:{line_number} has invalid numeric data: {exc}") from exc

    return readings


def load_threshold_config(path: str | Path) -> ThresholdConfig:
    """Load and normalize warning/critical threshold config from JSON."""

    config_path = Path(path)
    with config_path.open(encoding="utf-8") as handle:
        raw_config = json.load(handle)

    raw_channels = raw_config.get("channels", raw_config)
    if not isinstance(raw_channels, dict):
        raise ValueError("threshold config must contain a channel mapping")

    thresholds: ThresholdConfig = {}
    for channel, channel_config in raw_channels.items():
        if not isinstance(channel_config, dict):
            raise ValueError(f"threshold config for {channel!r} must be an object")

        thresholds[channel] = {}
        for severity in ("warning", "critical"):
            severity_config = channel_config.get(severity)
            if not isinstance(severity_config, dict):
                raise ValueError(f"{channel!r} missing {severity!r} thresholds")

            thresholds[channel][severity] = {}
            for bound in BOUNDS:
                value = severity_config.get(bound)
                if value is None:
                    raise ValueError(f"{channel!r} missing {severity}.{bound} threshold")
                thresholds[channel][severity][bound] = float(value)

    return thresholds


def evaluate_reading(reading: TelemetryReading, thresholds: ThresholdConfig) -> dict[str, Any] | None:
    """Return an anomaly dictionary when a reading breaches a configured threshold."""

    channel_thresholds = thresholds.get(reading.channel)
    if channel_thresholds is None:
        return None

    for severity in SEVERITIES:
        severity_thresholds = channel_thresholds[severity]
        for bound in BOUNDS:
            threshold = severity_thresholds[bound]
            if _breaches(reading.value, bound, threshold):
                return _build_anomaly(reading, severity, bound, threshold)

    return None


def analyze_telemetry(readings: list[TelemetryReading], thresholds: ThresholdConfig) -> dict[str, Any]:
    """Build a complete report dictionary from readings and thresholds."""

    by_channel: dict[str, list[TelemetryReading]] = defaultdict(list)
    anomalies: list[dict[str, Any]] = []
    out_of_range_by_channel: dict[str, int] = defaultdict(int)
    warning_count = 0
    critical_count = 0

    for reading in readings:
        by_channel[reading.channel].append(reading)
        anomaly = evaluate_reading(reading, thresholds)
        if anomaly is None:
            continue

        anomalies.append(anomaly)
        out_of_range_by_channel[reading.channel] += 1
        if anomaly["severity"] == "critical":
            critical_count += 1
        else:
            warning_count += 1

    channel_stats = {
        channel: _channel_stats(channel_readings, out_of_range_by_channel[channel])
        for channel, channel_readings in sorted(by_channel.items())
    }

    return {
        "summary": {
            "total_readings": len(readings),
            "total_anomalies": len(anomalies),
            "warning_count": warning_count,
            "critical_count": critical_count,
            "channels_analyzed": len(channel_stats),
        },
        "channels": channel_stats,
        "anomalies": sorted(anomalies, key=lambda item: (item["timestamp_ms"], item["channel"])),
    }


def _require_cell(row: dict[str, str | None], column: str) -> str:
    value = row.get(column)
    if value is None or value.strip() == "":
        raise ValueError(f"{column} is required")
    return value.strip()


def _breaches(value: float, bound: str, threshold: float) -> bool:
    if bound == "min":
        return value < threshold
    return value > threshold


def _build_anomaly(reading: TelemetryReading, severity: str, bound: str, threshold: float) -> dict[str, Any]:
    direction = "fell below" if bound == "min" else "exceeded"
    return {
        "timestamp_ms": reading.timestamp_ms,
        "channel": reading.channel,
        "value": reading.value,
        "unit": reading.unit,
        "threshold_breached": f"{severity} {bound} {threshold}",
        "severity": severity,
        "description": (
            f"{reading.channel} value {reading.value} {reading.unit} {direction} "
            f"{severity} {bound} threshold {threshold}"
        ),
    }


def _channel_stats(readings: list[TelemetryReading], out_of_range_count: int) -> dict[str, Any]:
    values = [reading.value for reading in readings]
    return {
        "count": len(values),
        "mean": statistics.fmean(values),
        "std_dev": statistics.pstdev(values) if len(values) > 1 else 0.0,
        "min": min(values),
        "max": max(values),
        "percent_out_of_range": (out_of_range_count / len(values)) * 100.0,
        "unit": readings[0].unit,
    }
