import json

import pytest

from analyzer import (
    TelemetryReading,
    analyze_telemetry,
    evaluate_reading,
    load_threshold_config,
    parse_telemetry_csv,
)


def test_parse_csv_converts_required_fields(tmp_path):
    csv_path = tmp_path / "telemetry.csv"
    csv_path.write_text(
        "timestamp_ms,channel,value,unit\n"
        "100,engine_temp_c,91.5,C\n"
        "200,battery_voltage_v,12.4,V\n",
        encoding="utf-8",
    )

    readings = parse_telemetry_csv(csv_path)

    assert readings == [
        TelemetryReading(100, "engine_temp_c", 91.5, "C"),
        TelemetryReading(200, "battery_voltage_v", 12.4, "V"),
    ]


def test_parse_csv_rejects_missing_required_columns(tmp_path):
    csv_path = tmp_path / "bad.csv"
    csv_path.write_text("timestamp_ms,channel,value\n100,engine_temp_c,91.5\n", encoding="utf-8")

    with pytest.raises(ValueError, match="missing required columns"):
        parse_telemetry_csv(csv_path)


def test_load_threshold_config_normalizes_channel_thresholds(tmp_path):
    config_path = tmp_path / "thresholds.json"
    config_path.write_text(
        json.dumps(
            {
                "channels": {
                    "engine_temp_c": {
                        "warning": {"min": 70, "max": 100},
                        "critical": {"min": 60, "max": 110},
                    }
                }
            }
        ),
        encoding="utf-8",
    )

    thresholds = load_threshold_config(config_path)

    assert thresholds["engine_temp_c"]["warning"]["min"] == 70.0
    assert thresholds["engine_temp_c"]["critical"]["max"] == 110.0


def test_evaluate_reading_flags_critical_before_warning():
    thresholds = {
        "engine_temp_c": {
            "warning": {"min": 70.0, "max": 100.0},
            "critical": {"min": 60.0, "max": 110.0},
        }
    }
    reading = TelemetryReading(1000, "engine_temp_c", 115.0, "C")

    anomaly = evaluate_reading(reading, thresholds)

    assert anomaly is not None
    assert anomaly["timestamp_ms"] == 1000
    assert anomaly["channel"] == "engine_temp_c"
    assert anomaly["value"] == 115.0
    assert anomaly["threshold_breached"] == "critical max 110.0"
    assert anomaly["severity"] == "critical"
    assert "engine_temp_c value 115.0 C exceeded critical max threshold 110.0" in anomaly["description"]


def test_evaluate_reading_flags_warning_when_inside_critical_range():
    thresholds = {
        "battery_voltage_v": {
            "warning": {"min": 11.8, "max": 14.6},
            "critical": {"min": 10.5, "max": 15.5},
        }
    }
    reading = TelemetryReading(500, "battery_voltage_v", 11.2, "V")

    anomaly = evaluate_reading(reading, thresholds)

    assert anomaly is not None
    assert anomaly["threshold_breached"] == "warning min 11.8"
    assert anomaly["severity"] == "warning"


def test_analyze_telemetry_aggregates_stats_and_anomalies():
    thresholds = {
        "engine_temp_c": {
            "warning": {"min": 70.0, "max": 100.0},
            "critical": {"min": 60.0, "max": 110.0},
        },
        "battery_voltage_v": {
            "warning": {"min": 11.8, "max": 14.6},
            "critical": {"min": 10.5, "max": 15.5},
        },
    }
    readings = [
        TelemetryReading(100, "engine_temp_c", 80.0, "C"),
        TelemetryReading(200, "engine_temp_c", 100.0, "C"),
        TelemetryReading(300, "engine_temp_c", 120.0, "C"),
        TelemetryReading(400, "battery_voltage_v", 12.5, "V"),
        TelemetryReading(500, "battery_voltage_v", 11.2, "V"),
    ]

    report = analyze_telemetry(readings, thresholds)

    assert report["summary"] == {
        "total_readings": 5,
        "total_anomalies": 2,
        "warning_count": 1,
        "critical_count": 1,
        "channels_analyzed": 2,
    }
    assert report["channels"]["engine_temp_c"]["count"] == 3
    assert report["channels"]["engine_temp_c"]["mean"] == 100.0
    assert report["channels"]["engine_temp_c"]["std_dev"] == pytest.approx(16.3299, rel=1e-4)
    assert report["channels"]["engine_temp_c"]["min"] == 80.0
    assert report["channels"]["engine_temp_c"]["max"] == 120.0
    assert report["channels"]["engine_temp_c"]["percent_out_of_range"] == pytest.approx(33.3333, rel=1e-4)
    assert [item["severity"] for item in report["anomalies"]] == ["critical", "warning"]
