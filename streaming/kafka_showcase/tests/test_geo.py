"""Tests for the geo-cell binning that the Spark windowed agg mirrors in SQL."""

from __future__ import annotations

import pytest

from spark_app.geo import DEFAULT_CELL_SIZE_DEG, cell_index, cell_of, in_us_bbox


def test_cell_index_snaps_to_lower_left():
    # 41.97 with 0.5 cells -> floor(41.97/0.5)*0.5 = 41.5
    assert cell_index(41.97, 0.5) == pytest.approx(41.5)
    # -87.90 -> floor(-87.90/0.5)*0.5 = floor(-175.8)*0.5 = -176*0.5 = -88.0
    assert cell_index(-87.90, 0.5) == pytest.approx(-88.0)


def test_cell_index_matches_spark_floor_expression():
    # Spark uses floor(value/size)*size; verify negative-number behavior matches
    # (floor rounds toward -inf, not toward zero).
    import math

    for v in (24.0, 49.99, -66.0, -124.9, 0.3, -0.3):
        expected = math.floor(v / 0.5) * 0.5
        assert cell_index(v, 0.5) == pytest.approx(expected)


def test_cell_of_returns_pair():
    lat_cell, lon_cell = cell_of(41.97, -87.90)
    assert lat_cell == pytest.approx(41.5)
    assert lon_cell == pytest.approx(-88.0)


def test_default_cell_size():
    assert DEFAULT_CELL_SIZE_DEG == 0.5


def test_in_us_bbox():
    assert in_us_bbox(41.97, -87.90)        # Chicago area: inside
    assert in_us_bbox(24.0, -125.0)         # corner inclusive
    assert in_us_bbox(50.0, -66.0)          # corner inclusive
    assert not in_us_bbox(51.0, -100.0)     # too far north
    assert not in_us_bbox(40.0, -130.0)     # too far west
