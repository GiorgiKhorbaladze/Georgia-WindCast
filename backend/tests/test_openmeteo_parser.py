import copy
import json
from datetime import UTC, datetime

import pytest

from app.ingestion.openmeteo import (
    FORECAST,
    REANALYSIS,
    UNSUPPORTED_HEIGHTS,
    OpenMeteoError,
    archive_url,
    forecast_url,
    hourly_variables,
    parse_response,
    parse_run_time,
)
from app.sites import SITES
from tests.weather_fixtures import (
    REAL_ARCHIVE,
    REAL_ARCHIVE_BYTES,
    REAL_FORECAST_BYTES,
    REAL_META_BYTES,
    forecast_like,
    meta,
)


def dumps(obj) -> bytes:
    return json.dumps(obj).encode()


def test_real_archive_three_sites_in_request_order():
    series = parse_response(REAL_ARCHIVE_BYTES, 3, REANALYSIS.heights)
    assert len(series) == 3
    first = series[0].by_height[100][0]
    assert first.valid_at == datetime(2026, 11, 6, 0, tzinfo=UTC)
    assert first.speed_ms == 6.75 and first.direction_deg == 282
    assert len(series[0].by_height[10]) == 48


def test_era5_grid_cell_is_shared_by_ruisi_and_kartli():
    """Documented limitation: ERA5's ~25 km grid puts both farms in one cell."""
    series = parse_response(REAL_ARCHIVE_BYTES, 3, REANALYSIS.heights)
    ruisi, zemo, kartli = series
    assert (ruisi.grid_latitude, ruisi.grid_longitude) == (
        kartli.grid_latitude,
        kartli.grid_longitude,
    )
    assert (zemo.grid_latitude, zemo.grid_longitude) != (ruisi.grid_latitude, ruisi.grid_longitude)


def test_real_forecast_three_sites_four_heights_96_hours():
    series = parse_response(REAL_FORECAST_BYTES, 3, FORECAST.heights)
    ruisi, zemo, kartli = series
    assert set(ruisi.by_height) == {10, 80, 120, 180}
    assert len(ruisi.by_height[120]) == 96
    first = ruisi.by_height[10][0]
    assert first.valid_at == datetime(2026, 11, 15, 0, tzinfo=UTC)
    assert (first.speed_ms, first.direction_deg) == (1.92, 261)
    # Documented limitation: ICON global (0.125 deg) also maps Ruisi and Kartli to one grid point.
    assert (ruisi.grid_latitude, ruisi.grid_longitude) == (
        kartli.grid_latitude,
        kartli.grid_longitude,
    )
    assert (zemo.grid_latitude, zemo.grid_longitude) == (41.875, 44.375)


def test_real_run_metadata():
    assert parse_run_time(REAL_META_BYTES) == datetime(2026, 11, 14, 18, tzinfo=UTC)


def test_forecast_heights_and_unsupported():
    assert FORECAST.heights == (10, 80, 120, 180)
    assert REANALYSIS.heights == (10, 100)
    assert UNSUPPORTED_HEIGHTS == (200,)
    series = parse_response(dumps(forecast_like()), 3, FORECAST.heights)
    assert set(series[0].by_height) == {10, 80, 120, 180}


def test_single_location_object_is_accepted():
    series = parse_response(dumps(REAL_ARCHIVE[0]), 1, REANALYSIS.heights)
    assert len(series) == 1


def test_nulls_are_kept_as_missing():
    data = copy.deepcopy(REAL_ARCHIVE)
    data[0]["hourly"]["wind_speed_100m"][5] = None
    data[0]["hourly"]["wind_direction_100m"][5] = None
    v = parse_response(dumps(data), 3, REANALYSIS.heights)[0].by_height[100][5]
    assert v.speed_ms is None and v.direction_deg is None


@pytest.mark.parametrize(
    ("mutate", "match"),
    [
        (lambda d: d[0]["hourly_units"].__setitem__("wind_speed_10m", "km/h"), "unit"),
        (lambda d: d[0]["hourly_units"].__setitem__("time", "iso8601"), "time format"),
        (lambda d: d[0]["hourly"].pop("wind_speed_100m"), "missing"),
        (lambda d: d[0]["hourly"]["wind_speed_10m"].pop(), "length"),
        (lambda d: d[0]["hourly"]["wind_speed_10m"].__setitem__(0, -1.0), "out-of-range"),
        (lambda d: d[0]["hourly"]["wind_direction_10m"].__setitem__(0, 400), "out-of-range"),
        (lambda d: d[0]["hourly"]["wind_speed_10m"].__setitem__(0, "fast"), "non-numeric"),
        (lambda d: d.pop(), "expected 3 locations"),
    ],
)
def test_schema_and_value_violations(mutate, match):
    data = copy.deepcopy(REAL_ARCHIVE)
    mutate(data)
    with pytest.raises(OpenMeteoError, match=match):
        parse_response(dumps(data), 3, REANALYSIS.heights)


def test_provider_error_payload():
    body = dumps({"error": True, "reason": "Daily API request limit exceeded."})
    with pytest.raises(OpenMeteoError, match="limit exceeded"):
        parse_response(body, 3, REANALYSIS.heights)


def test_not_json():
    with pytest.raises(OpenMeteoError, match="not JSON"):
        parse_response(b"<html>", 3, REANALYSIS.heights)


def test_run_time():
    assert parse_run_time(meta(1794668400)) == datetime(2026, 11, 14, 15, tzinfo=UTC)
    with pytest.raises(OpenMeteoError):
        parse_run_time(b"{}")


def test_urls_carry_all_sites_once_and_ms_units():
    url = forecast_url("https://api.open-meteo.com", SITES, 4)
    assert url.startswith("https://api.open-meteo.com/v1/forecast?")
    assert "latitude=42.055596,41.895560,42.022423" in url
    assert "wind_speed_unit=ms" in url and "models=icon_global" in url
    assert "wind_speed_200m" not in url and "wind_speed_100m" not in url
    a = archive_url("https://archive-api.open-meteo.com", SITES, "2026-11-01", "2026-11-10")
    assert "models=era5" in a and "wind_speed_100m" in a
    assert hourly_variables((10,)) == ["wind_speed_10m", "wind_direction_10m"]
