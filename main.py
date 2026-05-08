"""Command-line entrypoint for vehicle telemetry threshold analysis."""

from __future__ import annotations

import argparse
from pathlib import Path

from analyzer import analyze_telemetry, load_threshold_config, parse_telemetry_csv
from reporter import write_html_report, write_json_report


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Analyze vehicle ECU telemetry CSV readings against channel threshold config."
    )
    parser.add_argument("--input", required=True, help="Path to telemetry CSV input file.")
    parser.add_argument("--config", required=True, help="Path to JSON threshold configuration.")
    parser.add_argument("--output", required=True, help="Directory where reports should be written.")
    return parser


def main() -> int:
    args = build_parser().parse_args()

    readings = parse_telemetry_csv(Path(args.input))
    thresholds = load_threshold_config(Path(args.config))
    report = analyze_telemetry(readings, thresholds)

    json_path = write_json_report(report, args.output)
    html_path = write_html_report(report, args.output)

    print(f"JSON report written to: {json_path}")
    print(f"HTML report written to: {html_path}")
    print(
        "Analyzed "
        f"{report['summary']['total_readings']} readings, "
        f"flagged {report['summary']['total_anomalies']} anomalies."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
