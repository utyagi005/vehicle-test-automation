import json

from reporter import generate_html_report, write_html_report, write_json_report


def test_write_json_report_creates_pretty_json(tmp_path):
    report = {
        "summary": {"total_readings": 1, "total_anomalies": 0},
        "channels": {},
        "anomalies": [],
    }

    output_path = write_json_report(report, tmp_path)

    assert output_path == tmp_path / "report.json"
    assert json.loads(output_path.read_text(encoding="utf-8")) == report
    assert output_path.read_text(encoding="utf-8").startswith("{\n  ")


def test_write_html_report_contains_summary_stats_and_escaped_anomalies(tmp_path):
    report = {
        "summary": {
            "total_readings": 2,
            "total_anomalies": 1,
            "warning_count": 1,
            "critical_count": 0,
            "channels_analyzed": 1,
        },
        "channels": {
            "engine_temp_c": {
                "count": 2,
                "mean": 95.0,
                "std_dev": 5.0,
                "min": 90.0,
                "max": 100.0,
                "percent_out_of_range": 50.0,
                "unit": "C",
            }
        },
        "anomalies": [
            {
                "timestamp_ms": 200,
                "channel": "engine_temp_c",
                "value": 101.0,
                "unit": "C",
                "threshold_breached": "warning max 100.0",
                "severity": "warning",
                "description": "engine_temp_c <hot> exceeded warning max threshold 100.0",
            }
        ],
    }

    output_path = write_html_report(report, tmp_path)
    html = output_path.read_text(encoding="utf-8")

    assert output_path == tmp_path / "report.html"
    assert "<!doctype html>" in html.lower()
    assert "Vehicle ECU Telemetry Test Report" in html
    assert "engine_temp_c" in html
    assert "50.00%" in html
    assert "&lt;hot&gt;" in html


def test_generate_html_report_handles_empty_anomaly_list():
    report = {
        "summary": {
            "total_readings": 1,
            "total_anomalies": 0,
            "warning_count": 0,
            "critical_count": 0,
            "channels_analyzed": 1,
        },
        "channels": {
            "battery_voltage_v": {
                "count": 1,
                "mean": 12.6,
                "std_dev": 0.0,
                "min": 12.6,
                "max": 12.6,
                "percent_out_of_range": 0.0,
                "unit": "V",
            }
        },
        "anomalies": [],
    }

    html = generate_html_report(report)

    assert "No anomalies detected" in html
    assert "battery_voltage_v" in html
