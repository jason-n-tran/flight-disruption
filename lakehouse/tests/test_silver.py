"""Silver-stage tests: derivations + filtering."""

from __future__ import annotations


def test_dep_hour_and_bucket_derivation(spark, synthetic_lake):
    from flight_lakehouse.silver import build_silver

    out = build_silver(spark, synthetic_lake)
    flights = out["flights"]

    rows = {
        (r["flight_date"].isoformat(), r["dep_hour"]): r
        for r in flights.collect()
    }

    # crs_dep_time 1430 -> dep_hour 14 -> afternoon
    probe = rows[("2024-01-12", 14)]
    assert probe["dep_hour"] == 14
    assert probe["time_of_day_bucket"] == "afternoon"

    # 0800 -> morning, 1700 -> afternoon, 0900 -> morning
    assert rows[("2024-01-10", 8)]["time_of_day_bucket"] == "morning"
    assert rows[("2024-01-10", 17)]["time_of_day_bucket"] == "afternoon"
    assert rows[("2024-01-11", 9)]["time_of_day_bucket"] == "morning"


def test_carrier_rename_and_label(spark, synthetic_lake):
    from flight_lakehouse.silver import build_silver

    out = build_silver(spark, synthetic_lake)
    flights = out["flights"]

    assert "carrier" in flights.columns
    assert "reporting_airline" not in flights.columns
    assert set(r["carrier"] for r in flights.collect()) == {"ZZ"}

    # label preserved, integer 0/1
    labels = sorted(r["dep_del15"] for r in flights.collect())
    assert labels == [0, 0, 1, 1]


def test_silver_carries_columns_dbt_staging_needs(spark, synthetic_lake):
    """Guard against silver/dbt schema drift: stg_flights references these
    columns by name, so silver MUST emit them (a missing one is a hard dbt
    Binder Error at run time, not a test failure — hence this explicit check)."""
    from flight_lakehouse.silver import build_silver

    flights = build_silver(spark, synthetic_lake)["flights"]
    required = {
        "flight_date", "year", "month", "day_of_week", "dep_hour",
        "time_of_day_bucket", "carrier", "flight_number_reporting_airline",
        "origin", "dest", "distance", "crs_dep_time", "crs_arr_time",
        "crs_elapsed_time", "dep_del15", "dep_delay_minutes", "arr_del15",
        "cancelled", "diverted", "carrier_delay", "weather_delay", "nas_delay",
        "security_delay", "late_aircraft_delay", "is_holiday_window",
    }
    missing = required - set(flights.columns)
    assert not missing, f"silver/flights missing columns dbt needs: {sorted(missing)}"


def test_holiday_window_flag(spark, synthetic_lake):
    from flight_lakehouse.silver import build_silver

    out = build_silver(spark, synthetic_lake)
    flights = out["flights"]
    # Jan 10-12 2024 are NOT within +/-2 days of a federal holiday (MLK is
    # 2024-01-15, window 13-17). So all flags should be 0.
    flags = set(r["is_holiday_window"] for r in flights.collect())
    assert flags == {0}


def test_row_count_and_valid_iata(spark, synthetic_lake):
    from flight_lakehouse.silver import build_silver

    out = build_silver(spark, synthetic_lake)
    # all 4 synthetic flights have valid origin/dest + non-null label
    assert out["flights"].count() == 4
    assert out["airports"].count() == 3
