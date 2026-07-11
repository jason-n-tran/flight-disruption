"""Pure geo helpers for the congestion aggregation.

Kept Spark-free so the cell-binning logic is unit-testable. The Spark job
expresses the *same* binning as SQL column expressions (``floor(lat/size)*size``)
so the streaming aggregation and these helpers stay consistent — the tests pin
the contract.
"""

from __future__ import annotations

from flight_contracts import US_BBOX

# Aggregation granularity: ~0.5 deg geo-cells (≈ 55 km N-S). Coarse enough that
# busy terminal areas (the metros around major airports) light up as congestion
# hotspots, fine enough to distinguish them. Override-able by the Spark job.
DEFAULT_CELL_SIZE_DEG = 0.5


def cell_index(value: float, cell_size: float = DEFAULT_CELL_SIZE_DEG) -> float:
    """Snap a lat or lon to the lower-left corner of its cell.

    Mirrors the Spark expression ``floor(value / cell_size) * cell_size``.
    """
    import math

    return math.floor(value / cell_size) * cell_size


def cell_of(
    lat: float, lon: float, cell_size: float = DEFAULT_CELL_SIZE_DEG
) -> tuple[float, float]:
    """Return the ``(cell_lat, cell_lon)`` key for a position."""
    return cell_index(lat, cell_size), cell_index(lon, cell_size)


def in_us_bbox(lat: float, lon: float) -> bool:
    """True if a position falls inside the continental-US bbox (contract)."""
    return (
        US_BBOX.lamin <= lat <= US_BBOX.lamax
        and US_BBOX.lomin <= lon <= US_BBOX.lomax
    )
