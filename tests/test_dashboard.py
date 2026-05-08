import json
import threading
import urllib.request

from dashboard_server import (
    DashboardTelemetrySimulator,
    DashboardHTTPServer,
    DASHBOARD_HTML,
    DASHBOARD_JS,
    build_export_report,
    create_handler,
    encode_sse,
    load_dashboard_config,
)


def test_simulator_generates_reading_events_with_anomaly_metadata(tmp_path):
    config_path = tmp_path / "thresholds.json"
    config_path.write_text(
        json.dumps(
            {
                "channels": {
                    "engine_temp_c": {
                        "warning": {"min": 70.0, "max": 100.0},
                        "critical": {"min": 60.0, "max": 110.0},
                    }
                }
            }
        ),
        encoding="utf-8",
    )
    thresholds = load_dashboard_config(config_path)
    simulator = DashboardTelemetrySimulator(thresholds, seed=7)

    event = simulator.next_event()

    assert event["type"] == "reading"
    assert event["timestamp_ms"] == 0
    assert event["channel"] == "engine_temp_c"
    assert event["unit"] == "C"
    assert isinstance(event["value"], float)
    assert event["severity"] in {"normal", "warning", "critical"}
    assert "limits" in event


def test_encode_sse_formats_named_json_event():
    payload = {"channel": "battery_voltage_v", "value": 12.6}

    encoded = encode_sse("reading", payload)

    assert encoded.startswith("event: reading\n")
    assert 'data: {"channel": "battery_voltage_v", "value": 12.6}\n\n' == encoded.split("event: reading\n", 1)[1]


def test_build_export_report_reuses_analyzer_stats():
    readings = [
        {"timestamp_ms": 0, "channel": "engine_temp_c", "value": 90.0, "unit": "C"},
        {"timestamp_ms": 100, "channel": "engine_temp_c", "value": 115.0, "unit": "C"},
        {"timestamp_ms": 200, "channel": "battery_voltage_v", "value": 12.4, "unit": "V"},
    ]
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

    report = build_export_report(readings, thresholds)

    assert report["summary"]["total_readings"] == 3
    assert report["summary"]["critical_count"] == 1
    assert report["channels"]["engine_temp_c"]["percent_out_of_range"] == 50.0
    assert report["anomalies"][0]["threshold_breached"] == "critical max 110.0"


def test_dashboard_shell_includes_advanced_apple_style_controls():
    assert 'id="health-score"' in DASHBOARD_HTML
    assert 'id="stream-rate"' in DASHBOARD_HTML
    assert 'id="channel-filter"' in DASHBOARD_HTML
    assert 'data-filter="all"' in DASHBOARD_HTML
    assert 'id="clear-feed-button"' in DASHBOARD_HTML


def test_dashboard_client_updates_health_score_and_channel_focus():
    assert "function updateHealthScore()" in DASHBOARD_JS
    assert "function setChannelFilter(channel)" in DASHBOARD_JS
    assert "function updateRollingStats(channel)" in DASHBOARD_JS
    assert "function updateVisibleFeedCount()" in DASHBOARD_JS
    assert "drawThresholdBand" in DASHBOARD_JS


def test_limited_sse_stream_closes_after_requested_event_count():
    thresholds = {
        "engine_temp_c": {
            "warning": {"min": 70.0, "max": 100.0},
            "critical": {"min": 60.0, "max": 110.0},
        }
    }
    server = DashboardHTTPServer(("127.0.0.1", 0), create_handler(thresholds, seed=1, interval_ms=1))
    server.quiet = True
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()

    try:
        url = f"http://127.0.0.1:{server.server_port}/stream?limit=2"
        with urllib.request.urlopen(url, timeout=1) as response:
            body = response.read().decode("utf-8")
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=1)

    assert body.count("event: reading") == 2
