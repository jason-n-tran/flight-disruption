"""Gold-stage tests: leakage-safe rolling features + contract enforcement."""

from __future__ import annotations

import math

from flight_contracts.contract import (
    BANNED_LEAKY_COLUMNS,
    LABEL_COLUMN,
    MODEL_FEATURES,
)


def _build_gold(spark, cfg):
    from flight_lakehouse.gold_features import IDENTITY_COLUMNS, build_gold_features
    from flight_lakehouse.silver import build_silver

    build_silver(spark, cfg)
    gold = build_gold_features(spark, cfg)
    return gold, IDENTITY_COLUMNS


def test_contract_columns_exact(spark, synthetic_lake):
    gold, identity = _build_gold(spark, synthetic_lake)
    expected = set(MODEL_FEATURES) | {LABEL_COLUMN} | set(identity)
    assert set(gold.columns) == expected


def test_no_banned_columns(spark, synthetic_lake):
    import re

    def snake(name):
        s = name.replace("__", "_")
        s = re.sub(r"(.)([A-Z][a-z]+)", r"\1_\2", s)
        s = re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", s)
        return s.replace("__", "_").lower()

    gold, _ = _build_gold(spark, synthetic_lake)
    banned = {snake(c) for c in BANNED_LEAKY_COLUMNS}
    assert banned.isdisjoint(set(gold.columns))


def test_leakage_safe_rolling_feature(spark, synthetic_lake):
    """origin_hist_delay_rate must reflect ONLY strictly-earlier flights.

    Synthetic AAA timeline:
      01-10 : dep_del15 = [1, 1]   (earliest day -> no prior -> global prior)
      01-11 : dep_del15 = [0]      (prior = 01-10 -> mean(1,1) = 1.0)
      01-12 : dep_del15 = [0]      (prior = 01-10,01-11 -> mean(1,1,0) = 2/3)
    """
    gold, _ = _build_gold(spark, synthetic_lake)
    rows = {r["flight_date"].isoformat(): r for r in gold.collect()}

    # Global prior = overall mean label = (1+1+0+0)/4 = 0.5
    global_prior = 0.5

    # 01-10 flights: no AAA history before that day -> global prior fill.
    r10 = rows["2024-01-10"]
    assert math.isclose(r10["origin_hist_delay_rate"], global_prior, abs_tol=1e-9)

    # 01-11: prior = the two 01-10 flights, both delayed -> 1.0
    r11 = rows["2024-01-11"]
    assert math.isclose(r11["origin_hist_delay_rate"], 1.0, abs_tol=1e-9)

    # 01-12 (probe): prior = 01-10 (1,1) + 01-11 (0) -> mean = 2/3
    r12 = rows["2024-01-12"]
    assert math.isclose(r12["origin_hist_delay_rate"], 2.0 / 3.0, abs_tol=1e-9)


def test_route_and_carrier_hist_present_and_bounded(spark, synthetic_lake):
    gold, _ = _build_gold(spark, synthetic_lake)
    for r in gold.collect():
        for col in (
            "route_hist_delay_rate",
            "origin_hist_delay_rate",
            "carrier_hist_delay_rate",
        ):
            assert r[col] is not None
            assert 0.0 <= r[col] <= 1.0


def test_weather_join_and_fill(spark, synthetic_lake):
    """The probe flight (01-12, hour 14, origin AAA) has matching weather;
    others fall back to defaults."""
    from flight_lakehouse.gold_features import WEATHER_FILL

    gold, _ = _build_gold(spark, synthetic_lake)
    rows = {r["flight_date"].isoformat(): r for r in gold.collect()}

    probe = rows["2024-01-12"]
    assert math.isclose(probe["origin_temp_2m"], 5.5, abs_tol=1e-9)
    assert math.isclose(probe["origin_precip"], 1.2, abs_tol=1e-9)
    assert math.isclose(probe["origin_wind_speed"], 22.0, abs_tol=1e-9)
    assert math.isclose(probe["origin_snowfall"], 0.4, abs_tol=1e-9)

    # 01-11 flight has no matching weather hour -> defaults.
    r11 = rows["2024-01-11"]
    assert math.isclose(r11["origin_temp_2m"], WEATHER_FILL["temp_2m"], abs_tol=1e-9)
    assert math.isclose(r11["origin_precip"], WEATHER_FILL["precip"], abs_tol=1e-9)
    # dest weather always falls back here (no dest weather rows).
    assert math.isclose(probe["dest_precip"], WEATHER_FILL["precip"], abs_tol=1e-9)


def test_partitioned_by_year_written(spark, synthetic_lake):
    import glob
    import os

    from flight_contracts.contract import GOLD_FEATURES_TABLE

    _build_gold(spark, synthetic_lake)
    gold_dir = synthetic_lake.paths.gold_table(GOLD_FEATURES_TABLE)
    # year=2024 partition dir should exist
    assert os.path.isdir(os.path.join(gold_dir, "year=2024"))
    assert glob.glob(os.path.join(gold_dir, "year=2024", "*.parquet"))


def test_to_duckdb_lands_tables(spark, synthetic_lake):
    import duckdb

    from flight_contracts.contract import GOLD_AIRPORTS_DIM, GOLD_FEATURES_TABLE
    from flight_lakehouse.to_duckdb import parquet_to_duckdb

    _build_gold(spark, synthetic_lake)
    path = parquet_to_duckdb(synthetic_lake)

    con = duckdb.connect(path)
    try:
        n = con.execute(
            f'SELECT count(*) FROM "{GOLD_FEATURES_TABLE}"'
        ).fetchone()[0]
        assert n == 4
        airports = con.execute(
            f'SELECT count(*) FROM "{GOLD_AIRPORTS_DIM}"'
        ).fetchone()[0]
        assert airports == 3
    finally:
        con.close()
