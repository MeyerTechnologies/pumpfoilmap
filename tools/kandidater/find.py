#!/usr/bin/env python3
"""Finder potentielle pumpfoil-steder i OpenStreetMap og samler dem i kartoteket.

    python3 tools/kandidater/find.py          # bruger data/osm/raw.json
    python3 tools/kandidater/find.py --hent   # henter friske data fra Overpass først

Broer, flydebroer, badesteder, klubber m.m. der ligger tæt ved hinanden samles til ét sted.
Resultat:
  data/kandidater.csv       kartoteket: ét sted pr. række. Vurderinger bevares ved genkørsel,
                            og intet slettes – steder der forsvinder fra OSM markeres i 'osm_status'.
  data/kandidater-geo.json  OSM-geometri pr. sted (bruges af gennemgangssiden).
  data/kandidater-log.csv   én linje pr. kørsel (og pr. vurdering, se review.py).

Data © OpenStreetMap-bidragydere (ODbL).
"""
import argparse
import json
import math
import re
import subprocess
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from kartotek import (catalog_lock, ROOT, SPOTS_CSV, distance_m, fmt_coords, log, parse_coords, read_catalog,  # noqa: E402
                      read_csv, today, write_catalog)

RAW = ROOT / "data/osm/raw.json"
QUERY = ROOT / "data/osm/query.overpassql"
GEO = ROOT / "data/kandidater-geo.json"
SITE_RADIUS = 120      # m: objekter inden for denne afstand af stedets "frø" hører til stedet
NEAR_SPOT = 250        # m: steder så tæt på et eksisterende spot er allerede på kortet
OVERPASS = ["overpass-api.de", "overpass.private.coffee", "overpass.kumi.systems"]

# Kategori → vægt. Stedets prioritet (score) er den højeste vægt + lidt for hver ekstra kategori.
WEIGHTS = {
    "flydebro": 5, "kajakklub": 4, "roklub": 4, "sup": 3, "vinterbad": 3, "havnebad": 3,
    "badebro": 3, "badested": 2, "udlejning": 2, "bro": 1, "havn": 1, "slæbested": 1, "sejlklub": 1, "kanoplads": 1,
}
KEEP_TAGS = ("name", "man_made", "floating", "leisure", "sport", "amenity", "club", "access",
             "operator", "website", "description", "seasonal", "material", "surface")


def categorize(tags):
    name = tags.get("name", "").lower()
    sport = tags.get("sport", "").lower()
    leisure = tags.get("leisure", "")
    cats = set()
    if leisure in ("fitness_centre", "sports_hall", "swimming_pool", "water_park") \
            or re.search(r"padel|paddle_tennis", sport):
        return cats
    pier_like = tags.get("man_made") == "pier" or tags.get("floating") == "yes"
    if not pier_like and re.search(r"svømmehal|svømmebad|friluftsbad|(^|\s)hotel\b|reception|cafeteria", name):
        return cats  # bygninger og bassiner, ikke åbent vand
    if tags.get("type") == "route" or "route" in tags:
        return cats  # kano-/kajakruter er hele strækninger, ikke steder
    if "highway" in tags and tags.get("man_made") != "pier":
        return cats  # vejnavne som "Kajakvej" og "Badebrovej"
    if tags.get("floating") == "yes":
        cats.add("flydebro")
    if tags.get("man_made") == "pier":
        cats.add("bro")
        if re.search(r"badebro|badeanstalt|badested|bade", name):
            cats.add("badebro")
        if "flyde" in name or "ponton" in name:
            cats.add("flydebro")
    if leisure in ("bathing_place", "swimming_area"):
        cats.add("badested")
    if re.search(r"havnebad", name):
        cats.add("havnebad")
    if re.search(r"vinterbad|badeklub|søbad", name):
        cats.add("vinterbad")
    if re.search(r"canoe|kayak|paddle(?!_tennis)", sport) or re.search(r"kajak|kano(?!n)", name):
        # Kanolejr-, raste- og teltpladser langs åerne er sjældent relevante.
        # Kano-/kajakpladser langs åerne (bro, rast, lejr, overnatning) er sjældent relevante – lav vægt.
        kanoplads = r"lejr|raste|rast\b|telt|shelter|indsamling|opsamling|isætning|overnatning|kano ?plads|kanobro|kajakplads|kano- og kajakbro"
        cats.add("kanoplads" if re.search(kanoplads, name) else "kajakklub")
    if "rowing" in sport or re.search(r"roklub|\bro- og|roforening|roning", name):
        cats.add("roklub")
    if re.search(r"\bsup\b|stand_up_paddle", sport) or re.search(r"\bsup\b", name):
        cats.add("sup")
    if tags.get("amenity") == "boat_rental":
        cats.add("udlejning")
    if leisure == "marina":
        cats.add("havn")
    if leisure == "slipway":
        cats.add("slæbested")
    if "sejlklub" in name or "sejlforening" in name:
        cats.add("sejlklub")
    return cats


def element_point(el):
    if el["type"] == "node":
        return el["lat"], el["lon"]
    if el["type"] == "way" and el.get("geometry"):
        pts = el["geometry"]
        return sum(p["lat"] for p in pts) / len(pts), sum(p["lon"] for p in pts) / len(pts)
    if el.get("center"):
        return el["center"]["lat"], el["center"]["lon"]
    return None


def pier_length(el):
    pts = el.get("geometry") or []
    return sum(distance_m((a["lat"], a["lon"]), (b["lat"], b["lon"])) for a, b in zip(pts, pts[1:]))


class Grid:
    """Simpelt rumligt indeks, så vi ikke skal sammenligne alt med alt."""

    def __init__(self, cell_deg=0.01):
        self.cell = cell_deg
        self.cells = defaultdict(list)

    def key(self, p):
        return int(p[0] / self.cell), int(p[1] / self.cell)

    def add(self, p, item):
        self.cells[self.key(p)].append((p, item))

    def near(self, p, radius_m):
        ky, kx = self.key(p)
        span = 1 + int(radius_m / 600)
        for dy in range(-span, span + 1):
            for dx in range(-span, span + 1):
                for q, item in self.cells.get((ky + dy, kx + dx), ()):
                    d = distance_m(p, q)
                    if d <= radius_m:
                        yield d, item


def fetch():
    for host in OVERPASS:
        print(f"Henter fra {host} …", flush=True)
        res = subprocess.run(
            ["curl", "-s", "--max-time", "900", "-A", "pumpfoilmap (github.com/MeyerTechnologies/pumpfoilmap)",
             "--data-urlencode", f"data@{QUERY}", f"https://{host}/api/interpreter", "-o", str(RAW)])
        try:
            json.loads(RAW.read_text(encoding="utf-8"))
            return
        except Exception:
            print(f"  {host} svarede ikke med gyldige data", flush=True)
    sys.exit("Kunne ikke hente data fra Overpass.")


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--hent", action="store_true", help="hent friske data fra Overpass")
    args = parser.parse_args()
    if args.hent or not RAW.exists():
        fetch()

    raw = json.loads(RAW.read_text(encoding="utf-8"))
    places, elements = [], []
    for el in raw["elements"]:
        tags = el.get("tags", {})
        if "place" in tags and el["type"] == "node" and "man_made" not in tags and "leisure" not in tags:
            places.append(((el["lat"], el["lon"]), tags.get("name", ""), tags["place"]))
            continue
        cats = categorize(tags)
        pt = element_point(el)
        if not cats or not pt:
            continue
        ref = f"{el['type']}/{el['id']}"
        elements.append({
            "ref": ref, "pt": pt, "cats": cats, "tags": {k: v for k, v in tags.items() if k in KEEP_TAGS},
            "weight": max(WEIGHTS[c] for c in cats),
            "geom": [[round(p["lat"], 7), round(p["lon"], 7)] for p in el.get("geometry", [])] or None,
            "length": round(pier_length(el)) if el["type"] == "way" and tags.get("man_made") == "pier" else None,
        })
    by_ref = {e["ref"]: e for e in elements}

    # 1) Eksisterende steder i kartoteket beholder deres objekter (så id'er er stabile).
    catalog = read_catalog()
    grid = Grid()
    for e in elements:
        grid.add(e["pt"], e["ref"])
    assigned = {}
    for site in catalog:
        for ref in site["osm"].split():
            if ref in by_ref and ref not in assigned:
                assigned[ref] = site["id"]
    for site in catalog:
        seed_pt = parse_coords(site["auto_koordinater"])
        if not seed_pt:
            continue
        for _, ref in grid.near(seed_pt, SITE_RADIUS):
            assigned.setdefault(ref, site["id"])

    # 2) Nye steder: det vigtigste ikke-tildelte objekt bliver frø, og alt inden for SITE_RADIUS hører til.
    new_sites = {}
    for e in sorted(elements, key=lambda e: (-e["weight"], e["ref"])):
        if e["ref"] in assigned:
            continue
        sid = "k-" + e["ref"].replace("/", "")
        new_sites[sid] = e["pt"]
        for _, ref in grid.near(e["pt"], SITE_RADIUS):
            assigned.setdefault(ref, sid)

    members = defaultdict(list)
    for ref, sid in assigned.items():
        members[sid].append(by_ref[ref])

    # 3) Hjælpedata: nærmeste by og eksisterende spots.
    place_grid = Grid(0.05)
    for p, name, kind in places:
        if name:
            place_grid.add(p, (name, kind))
    spots = []
    for row in read_csv(SPOTS_CSV):
        pos = parse_coords(row.get("koordinater"))
        if pos:
            spots.append((pos, row.get("id", "")))
    spot_grid = Grid()
    for pos, sid in spots:
        spot_grid.add(pos, sid)

    def nearest_place(pt):
        best = min(place_grid.near(pt, 8000), default=None, key=lambda x: x[0])
        return best[1][0] if best else ""

    # 4) Opdatér kartoteket.
    existing = {s["id"]: s for s in catalog}
    geo = {}
    stats = defaultdict(int)
    for sid in list(existing) + [s for s in new_sites if s not in existing]:
        objs = sorted(members.get(sid, []), key=lambda e: (-e["weight"], e["ref"]))
        site = existing.get(sid) or {"id": sid, "vurdering": "", "type": "", "koordinater": "",
                                     "begrundelse": "", "vurderet": "", "fundet": today()}
        if not objs:
            if site.get("osm_status") != "forsvundet":
                site["osm_status"] = "forsvundet"
                stats["forsvundet"] += 1
            existing[sid] = site
            continue
        seed_pt = new_sites.get(sid) or parse_coords(site.get("auto_koordinater")) or objs[0]["pt"]
        cats = {c for o in objs for c in o["cats"]}
        if "badested" in cats and "bro" in cats:
            cats.add("badebro")  # et badested med bro er en badebro
        cats = sorted(cats, key=lambda c: (-WEIGHTS[c], c))
        named = [o["tags"]["name"] for o in objs if o["tags"].get("name")]
        site.update({
            "navn": named[0] if named else "",
            "område": nearest_place(seed_pt),
            "kategorier": " ".join(cats),
            "score": f"{WEIGHTS[cats[0]] + 0.5 * (len(cats) - 1):.1f}",
            "antal_objekter": str(len(objs)),
            "osm": " ".join(o["ref"] for o in objs),
            "auto_koordinater": fmt_coords(seed_pt),
            "osm_status": "ok",
        })
        near = min(spot_grid.near(seed_pt, NEAR_SPOT), default=None, key=lambda x: x[0])
        site["tæt_på_spot"] = near[1] if near else ""
        if near and not site["vurdering"]:
            site["vurdering"] = "på kortet"
        if sid not in existing:
            stats["nye"] += 1
        existing[sid] = site
        geo[sid] = [{"ref": o["ref"], "cats": sorted(o["cats"]), "tags": o["tags"], "pt": [round(o["pt"][0], 7), round(o["pt"][1], 7)],
                     **({"geom": o["geom"]} if o["geom"] else {}), **({"length": o["length"]} if o["length"] else {})}
                    for o in objs]

    rows = sorted(existing.values(), key=lambda s: (-float(s.get("score") or 0), s["id"]))
    write_catalog(rows)
    GEO.write_text(json.dumps(geo, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")

    counts = defaultdict(int)
    for s in rows:
        counts[s["vurdering"] or "ikke vurderet"] += 1
    summary = f"{len(rows)} steder ({stats['nye']} nye, {stats['forsvundet']} forsvundet fra OSM) · " + \
              ", ".join(f"{k}: {v}" for k, v in sorted(counts.items()))
    log("kørsel", "", "", "", f"find.py: {summary}")
    print(summary)


if __name__ == "__main__":
    with catalog_lock():
        main()
