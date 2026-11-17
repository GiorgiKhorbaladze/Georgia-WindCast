"""Wind direction as text. Pure functions, no Streamlit.

Meteorological convention, used everywhere in the app: the angle says where the wind blows FROM,
clockwise from north (0°/360° = from the north, 90° = from the east, 180° = from the south,
270° = from the west). Raw degrees are always kept next to the text; the sector is only an aid.
Direction is circular: neighbouring values 359° and 1° are 2° apart, never 358°.
"""

from __future__ import annotations

import math

# 8 sectors of 45°, centred on the cardinal and intercardinal points ("from" wording).
SECTORS = {
    "ka": ("ჩრდილოეთიდან", "ჩრდილო-აღმოსავლეთიდან", "აღმოსავლეთიდან", "სამხრეთ-აღმოსავლეთიდან",
           "სამხრეთიდან", "სამხრეთ-დასავლეთიდან", "დასავლეთიდან", "ჩრდილო-დასავლეთიდან"),
    "en": ("from north", "from north-east", "from east", "from south-east",
           "from south", "from south-west", "from west", "from north-west"),
}
# Short cardinal names for the direction axis (degree -> name of the side the wind comes from).
AXIS = {
    "ka": {0: "ჩრდ.", 90: "აღმ.", 180: "სამხ.", 270: "დას.", 360: "ჩრდ."},
    "en": {0: "N", 90: "E", 180: "S", 270: "W", 360: "N"},
}
CALM_MS = 3.0  # same threshold as the circular direction error in verification.py


def _valid(deg) -> bool:
    return deg is not None and not (isinstance(deg, float) and math.isnan(deg))


def normalize(deg: float) -> float:
    """Any angle -> [0, 360)."""
    return float(deg) % 360.0


def sector(deg, lang: str = "ka") -> str | None:
    """Localized 8-sector name ("from" wording); None for a missing value."""
    if not _valid(deg):
        return None
    idx = int(((normalize(deg) + 22.5) % 360) // 45)
    return SECTORS.get(lang, SECTORS["en"])[idx]


def label(deg, lang: str = "ka") -> str:
    """'270° - დასავლეთიდან' / '270° - from west'; '-' for a missing value."""
    if not _valid(deg):
        return "-"
    return f"{round(float(deg)) % 360:.0f}° - {sector(deg, lang)}"


def difference(a, b) -> float | None:
    """Smallest angle between two directions (0..180): difference(359, 1) == 2."""
    if not (_valid(a) and _valid(b)):
        return None
    d = abs(normalize(a) - normalize(b)) % 360
    return min(d, 360 - d)
