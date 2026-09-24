"""Fælles funktioner til kandidat-kartoteket (data/kandidater.csv og data/kandidater-log.csv)."""
import csv
import math
import re
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parent.parent.parent
CATALOG = ROOT / "data/kandidater.csv"
LOG = ROOT / "data/kandidater-log.csv"
SPOTS_CSV = ROOT / "data/spots.csv"
TZ = ZoneInfo("Europe/Copenhagen")

COLUMNS = [
    "id", "vurdering", "type", "navn", "område", "koordinater", "begrundelse", "vurderet",
    "kategorier", "score", "antal_objekter", "tæt_på_spot", "auto_koordinater", "osm", "osm_status", "fundet",
]
LOG_COLUMNS = ["tidspunkt", "id", "handling", "fra", "til", "note"]

# Vurderinger: tom = ikke vurderet endnu.
VURDERINGER = {
    "lovende": "Ligner et godt sted: lav bro/ponton på roligt, dybt vand",
    "måske": "Kan være brugbart, men noget er uklart (højde, dybde, adgang, billedet)",
    "nej": "Afvist – begrundelsen står i kolonnen 'begrundelse'",
    "på kortet": "Ligger allerede på kortet (tæt på et eksisterende spot)",
}


def today():
    return datetime.now(TZ).date().isoformat()


def now():
    return datetime.now(TZ).isoformat(timespec="seconds")


def distance_m(a, b):
    lat1, lon1, lat2, lon2 = map(math.radians, (a[0], a[1], b[0], b[1]))
    h = math.sin((lat2 - lat1) / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin((lon2 - lon1) / 2) ** 2
    return 2 * 6371000 * math.asin(math.sqrt(h))


def parse_coords(value):
    nums = re.findall(r"-?\d{1,3}\.\d+", value or "")
    if len(nums) < 2:
        return None
    return float(nums[0]), float(nums[1])


def fmt_coords(pt):
    return f"{pt[0]:.7f}, {pt[1]:.7f}"


def read_csv(path):
    if not Path(path).exists():
        return []
    with open(path, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def read_catalog():
    return [{c: row.get(c, "") for c in COLUMNS} for row in read_csv(CATALOG)]


def write_catalog(rows):
    tmp = CATALOG.with_suffix(".tmp")
    with open(tmp, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=COLUMNS, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)
    tmp.replace(CATALOG)


def log(handling, sid, fra, til, note=""):
    new = not LOG.exists()
    with open(LOG, "a", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        if new:
            writer.writerow(LOG_COLUMNS)
        writer.writerow([now(), sid, handling, fra, til, note])
