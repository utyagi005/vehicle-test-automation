# Vehicle Test Automation

A Python CLI tool for automated analysis of simulated vehicle ECU telemetry. It ingests CSV readings, validates each sensor channel against configurable warning and critical thresholds, flags anomalies, computes engineering statistics, and produces structured JSON plus self-contained HTML reports.

This project is designed to demonstrate the kind of practical automation used by vehicle test, validation, and controls teams: Python scripting, test data analysis, configurable checks, unit testing, and clear reporting for engineering partners.

## Highlights

- Parses ECU telemetry CSV files with `timestamp_ms`, `channel`, `value`, and `unit`.
- Supports JSON threshold configs per channel with warning and critical min/max limits.
- Flags warning and critical anomalies with timestamp, breached threshold, severity, and readable descriptions.
- Computes per-channel statistics: count, mean, population standard deviation, min, max, and percent out of range.
- Writes both machine-readable `report.json` and self-contained `report.html`.
- Includes a synthetic telemetry generator for realistic test runs.
- Uses only Python standard library at runtime. Tests use `pytest`.

## Project Structure

```text
vehicle-test-automation/
├── analyzer.py              # CSV parsing, threshold logic, anomaly detection, stats
├── reporter.py              # JSON and HTML report generation
├── main.py                  # argparse CLI entrypoint
├── generate_sample_data.py  # Synthetic ECU telemetry generator
├── config/
│   └── thresholds.json      # Example warning/critical channel thresholds
├── data/                    # Input telemetry CSVs
├── reports/                 # Generated JSON/HTML reports
└── tests/                   # pytest coverage for parsing, thresholds, anomalies, reports
```

## Quick Start

Create a virtual environment and install the test runner:

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements-dev.txt
```

Generate sample telemetry:

```bash
.venv/bin/python generate_sample_data.py --output data/telemetry.csv --rows 500 --seed 42
```

Run the analyzer:

```bash
.venv/bin/python main.py --input data/telemetry.csv --config config/thresholds.json --output reports/
```

Open `reports/report.html` in a browser or consume `reports/report.json` from another tool.

## Threshold Config Format

```json
{
  "channels": {
    "engine_temp_c": {
      "warning": { "min": 70.0, "max": 100.0 },
      "critical": { "min": 60.0, "max": 110.0 }
    }
  }
}
```

Critical thresholds are evaluated first. A value outside the critical band is flagged as `critical`; a value outside the warning band but still inside the critical band is flagged as `warning`.

## Example Output

The JSON report has three top-level sections:

- `summary`: total readings, anomaly counts, and channel count.
- `channels`: per-channel aggregate statistics.
- `anomalies`: timestamped warning/critical findings with threshold details.

The HTML report contains the same information in a readable, self-contained format that can be shared without any external assets or dependencies.

## Testing

Run the full test suite:

```bash
.venv/bin/python -m pytest -q
```

Coverage includes:

- CSV parsing and validation
- Threshold config normalization
- Warning vs. critical severity precedence
- Anomaly detection
- Per-channel statistics
- JSON and HTML report generation

## Why This Project Matters

Vehicle validation teams need fast, repeatable ways to turn raw test data into engineering decisions. This project models that workflow: ingest telemetry, apply configurable pass/fail criteria, summarize signal health, and produce reports that both automation systems and humans can use.
