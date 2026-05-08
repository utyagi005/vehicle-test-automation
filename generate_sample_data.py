"""Generate realistic synthetic ECU telemetry CSV files for testing."""

from __future__ import annotations

import argparse
import csv
import random
from pathlib import Path


CHANNEL_PROFILES = {
    "engine_temp_c": {"unit": "C", "mean": 91.0, "spread": 4.5, "warn_low": 64.0, "warn_high": 104.0},
    "battery_voltage_v": {"unit": "V", "mean": 12.8, "spread": 0.35, "warn_low": 11.4, "warn_high": 15.0},
    "vehicle_speed_kph": {"unit": "kph", "mean": 72.0, "spread": 24.0, "warn_low": -5.0, "warn_high": 132.0},
    "oil_pressure_kpa": {"unit": "kPa", "mean": 310.0, "spread": 42.0, "warn_low": 145.0, "warn_high": 575.0},
}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Generate synthetic vehicle ECU telemetry CSV data.")
    parser.add_argument("--output", default="data/telemetry.csv", help="CSV output path.")
    parser.add_argument("--rows", type=int, default=500, help="Number of readings to generate.")
    parser.add_argument("--seed", type=int, default=42, help="Random seed for reproducible datasets.")
    parser.add_argument("--interval-ms", type=int, default=100, help="Timestamp spacing between generated rows.")
    return parser


def generate_rows(row_count: int, interval_ms: int, rng: random.Random) -> list[dict[str, str]]:
    channels = list(CHANNEL_PROFILES)
    rows: list[dict[str, str]] = []

    for index in range(row_count):
        channel = channels[index % len(channels)]
        profile = CHANNEL_PROFILES[channel]
        value = rng.gauss(profile["mean"], profile["spread"])

        excursion_roll = rng.random()
        if excursion_roll < 0.025:
            value = profile["warn_high"] + abs(rng.gauss(profile["spread"], profile["spread"] / 2))
        elif excursion_roll < 0.05:
            value = profile["warn_low"] - abs(rng.gauss(profile["spread"], profile["spread"] / 2))

        if channel == "vehicle_speed_kph":
            value = max(0.0, value)

        rows.append(
            {
                "timestamp_ms": str(index * interval_ms),
                "channel": channel,
                "value": f"{value:.2f}",
                "unit": profile["unit"],
            }
        )

    return rows


def write_rows(rows: list[dict[str, str]], output_path: str | Path) -> Path:
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=["timestamp_ms", "channel", "value", "unit"])
        writer.writeheader()
        writer.writerows(rows)
    return path


def main() -> int:
    args = build_parser().parse_args()
    rng = random.Random(args.seed)
    output_path = write_rows(generate_rows(args.rows, args.interval_ms, rng), args.output)
    print(f"Wrote {args.rows} synthetic telemetry rows to {output_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
