"""US federal holidays 2015-2025, hardcoded to avoid a runtime dependency.

We only need the *observed* dates within the bronze span (2015-2025). The
silver stage flags a flight if its FlightDate falls within +/- 2 days of any of
these dates (``is_holiday_window``). Keeping this as a small literal set is
deliberate: it removes the ``holidays`` lib dependency for a deterministic,
auditable list, and federal dates are stable.

Dates are the observed federal holidays (the day off if it lands on a weekend),
which is what travel demand actually keys off of.
"""

from __future__ import annotations

# Observed US federal holidays, 2015-2025 inclusive.
US_FEDERAL_HOLIDAYS: list[str] = [
    # 2015
    "2015-01-01", "2015-01-19", "2015-02-16", "2015-05-25", "2015-07-03",
    "2015-09-07", "2015-10-12", "2015-11-11", "2015-11-26", "2015-12-25",
    # 2016
    "2016-01-01", "2016-01-18", "2016-02-15", "2016-05-30", "2016-07-04",
    "2016-09-05", "2016-10-10", "2016-11-11", "2016-11-24", "2016-12-26",
    # 2017
    "2017-01-02", "2017-01-16", "2017-02-20", "2017-05-29", "2017-07-04",
    "2017-09-04", "2017-10-09", "2017-11-10", "2017-11-23", "2017-12-25",
    # 2018
    "2018-01-01", "2018-01-15", "2018-02-19", "2018-05-28", "2018-07-04",
    "2018-09-03", "2018-10-08", "2018-11-12", "2018-11-22", "2018-12-25",
    # 2019
    "2019-01-01", "2019-01-21", "2019-02-18", "2019-05-27", "2019-07-04",
    "2019-09-02", "2019-10-14", "2019-11-11", "2019-11-28", "2019-12-25",
    # 2020
    "2020-01-01", "2020-01-20", "2020-02-17", "2020-05-25", "2020-07-03",
    "2020-09-07", "2020-10-12", "2020-11-11", "2020-11-26", "2020-12-25",
    # 2021
    "2021-01-01", "2021-01-18", "2021-02-15", "2021-05-31", "2021-06-18",
    "2021-07-05", "2021-09-06", "2021-10-11", "2021-11-11", "2021-11-25",
    "2021-12-24", "2021-12-31",
    # 2022 (Juneteenth now federal)
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
]


def holiday_window_dates(window_days: int = 2) -> set[str]:
    """Expand each holiday to its +/- ``window_days`` envelope (ISO date strings).

    Returns a flat set of every date that counts as "holiday window", so the
    silver stage can do a simple membership broadcast join / isin.
    """
    from datetime import date, timedelta

    out: set[str] = set()
    for d in US_FEDERAL_HOLIDAYS:
        y, m, dd = (int(x) for x in d.split("-"))
        base = date(y, m, dd)
        for off in range(-window_days, window_days + 1):
            out.add((base + timedelta(days=off)).isoformat())
    return out
