"""US federal holiday window for serve-time ``is_holiday_window``.

Mirrors ``lakehouse/flight_lakehouse/holidays.py`` (the training-time source of
truth) but is inlined here so the serving layer stays self-contained (the
lakehouse package is a heavy PySpark component and is not a serving dependency).

Extended through 2027 so predictions for upcoming/future dates still flag holiday
windows correctly (the training data only spans 2015-2025).
"""

from __future__ import annotations

from datetime import date, timedelta

# Observed US federal holidays (the day off if it lands on a weekend), 2022-2027.
# 2015-2021 omitted (no serve-time prediction targets that far back); 2022-2025
# match the lakehouse list exactly; 2026-2027 extend it for future predictions.
US_FEDERAL_HOLIDAYS: list[str] = [
    # 2022 (Juneteenth federal)
    "2022-01-01", "2022-01-17", "2022-02-21", "2022-05-30", "2022-06-20",
    "2022-07-04", "2022-09-05", "2022-10-10", "2022-11-11", "2022-11-24",
    "2022-12-26",
    # 2023
    "2023-01-02", "2023-01-16", "2023-02-20", "2023-05-29", "2023-06-19",
    "2023-07-04", "2023-09-04", "2023-10-09", "2023-11-10", "2023-11-23",
    "2023-12-25",
    # 2024
    "2024-01-01", "2024-01-15", "2024-02-19", "2024-05-27", "2024-06-19",
    "2024-07-04", "2024-09-02", "2024-10-14", "2024-11-11", "2024-11-28",
    "2024-12-25",
    # 2025
    "2025-01-01", "2025-01-20", "2025-02-17", "2025-05-26", "2025-06-19",
    "2025-07-04", "2025-09-01", "2025-10-13", "2025-11-11", "2025-11-27",
    "2025-12-25",
    # 2026
    "2026-01-01", "2026-01-19", "2026-02-16", "2026-05-25", "2026-06-19",
    "2026-07-03", "2026-09-07", "2026-10-12", "2026-11-11", "2026-11-26",
    "2026-12-25",
    # 2027
    "2027-01-01", "2027-01-18", "2027-02-15", "2027-05-31", "2027-06-18",
    "2027-07-05", "2027-09-06", "2027-10-11", "2027-11-11", "2027-11-25",
    "2027-12-24", "2027-12-31",
]


def _window(window_days: int = 2) -> set[str]:
    out: set[str] = set()
    for d in US_FEDERAL_HOLIDAYS:
        y, m, dd = (int(x) for x in d.split("-"))
        base = date(y, m, dd)
        for off in range(-window_days, window_days + 1):
            out.add((base + timedelta(days=off)).isoformat())
    return out


_WINDOW_DATES = _window(2)


def is_holiday_window(d: date) -> bool:
    """True if ``d`` falls within +/-2 days of a US federal holiday."""
    return d.isoformat() in _WINDOW_DATES
