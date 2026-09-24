#!/usr/bin/env python3
"""Bygger data og billeder til godkendelsessiden (tools/kandidater/godkend.html).

    python3 tools/kandidater/godkend_data.py

Resultat i tools/kandidater/.godkend/ (ikke i git): kandidater.json og s/NN.jpg.
Billederne kommer fra `review.py render --ren` og samles 20 ad gangen i fællesbilleder (sprites,
4×5 à 960×560) med ImageMagick, så siden holder sig under grænsen på 255 filer pr. version. Siden publiceres som Artifact på claude.ai,
og Go/No Go gemmes i dens database (samlingen 'beslutninger'). Se sync_beslutninger.py.
"""
import json
import math
import shutil
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from kartotek import LOG, ROOT, SPOTS_CSV, parse_coords, read_catalog, read_csv  # noqa: E402

HERE = Path(__file__).resolve().parent
OUT = HERE / ".godkend"
REN = HERE / ".screens/ren"
OUTLINE = HERE / "danmark.json"  # Danmarks omrids (Natural Earth 10m, public domain)

# Projektion til oversigtskortet: simpel lat/lon med cos(56°), Bornholm flyttet op i Kattegat som indsat kort.
PROJ = {"lon0": 7.95, "lat0": 57.85, "k": 200, "cos": math.cos(math.radians(56)),
        "inset": {"lonMin": 14.4, "dLon": -2.35, "dLat": 1.95}}
SPRITE = {"cols": 4, "rows": 5, "w": 960, "h": 560}
START = {"flydebro": "Dock", "ponton": "Dock", "badebro": "Dock", "bro": "Dock", "slæbested": "Andet", "strand": "Beach"}


def project(lat, lon):
    p = PROJ
    if lon >= p["inset"]["lonMin"]:
        lon, lat = lon + p["inset"]["dLon"], lat + p["inset"]["dLat"]
    return round((lon - p["lon0"]) * p["cos"] * p["k"], 1), round((p["lat0"] - lat) * p["k"], 1)


def outline_path():
    rings = json.loads(OUTLINE.read_text())
    parts = []
    for ring in rings:
        pts = [project(lat, lon) for lon, lat in ring]
        parts.append("M" + "L".join(f"{x},{y}" for x, y in pts) + "Z")
    return "".join(parts)


def split_badevand(text):
    """'Officielt sted …: 2025 udmærket · badevandsprofil: url · Regel: note (kilde)' → dele."""
    parts = [p.strip() for p in (text or "").split(" · ") if p.strip()]
    out = {"officielt": "", "profil": "", "forhold": []}
    for p in parts:
        if p.startswith("badevandsprofil: "):
            out["profil"] = p.split(": ", 1)[1]
        elif not out["officielt"]:
            out["officielt"] = p
        else:
            out["forhold"].append(p)
    return out


def main():
    OUT.mkdir(exist_ok=True)
    shutil.rmtree(OUT / "img", ignore_errors=True)
    shutil.rmtree(OUT / "s", ignore_errors=True)
    (OUT / "s").mkdir()
    # Steder der er lagt på kortet via kandidatkortet skal stadig kunne ses og rettes; de vises med den
    # vurdering, de havde, før de kom på kortet (fra loggen).
    before = {}
    for l in read_csv(LOG):
        if l["handling"] == "beslutning: med":
            before.setdefault(l["id"], l["fra"])
    rows = []
    for r in read_catalog():
        if r["osm_status"] == "forsvundet":
            continue
        if r["vurdering"] == "på kortet" and r["id"] in before:
            r = {**r, "vurdering": before[r["id"]] if before[r["id"]] in ("lovende", "måske", "nej") else "lovende"}
        if r["vurdering"] in ("lovende", "måske", "nej"):
            rows.append(r)
    order = {"lovende": 0, "måske": 1, "nej": 2}
    rows.sort(key=lambda r: (order[r["vurdering"]], -float(r["score"] or 0), r["id"]))
    candidates, missing = [], []
    for r in rows:
        pos = parse_coords(r["koordinater"]) or parse_coords(r["auto_koordinater"])
        img = REN / f"{r['id']}.jpg"
        if not img.exists():
            missing.append(r["id"])
        x, y = project(*pos)
        candidates.append({
            "id": r["id"], "navn": r["navn"], "omraade": r["område"], "vurdering": r["vurdering"],
            "type": r["type"], "begrundelse": r["begrundelse"], "pos": [round(pos[0], 7), round(pos[1], 7)],
            "xy": [x, y], "kategorier": r["kategorier"], "vurderet": r["vurderet"],
            "vand": r["vand"], "vandNote": r["vand_note"], "badevand": split_badevand(r["badevand"]),
            "start": START.get(r["type"], "Dock"), "img": str(img) if img.exists() else "",
            "osm": (r["osm"] or "").split(" ")[0],
        })
    # Fællesbilleder: 20 billeder pr. fil i kandidaternes rækkefølge.
    per = SPRITE["cols"] * SPRITE["rows"]
    # Kun lovende og måske får billede: siden må højst fylde 64 MB pr. version. Afviste steder viser et link
    # til satellitbilledet i Google Maps i stedet.
    with_img = [c for c in candidates if c["img"] and c["vurdering"] in ("lovende", "måske")]
    for n in range(0, len(with_img), per):
        group = with_img[n:n + per]
        name = f"s/{n // per:03d}.jpg"
        subprocess.run(["magick", "montage", *[c["img"] for c in group], "-tile", f"{SPRITE['cols']}x{SPRITE['rows']}",
                        "-geometry", f"{SPRITE['w']}x{SPRITE['h']}+0+0", "-background", "#1b2a2e",
                        "-quality", "64", str(OUT / name)], check=True)
        for i, c in enumerate(group):
            c["img"] = {"s": name, "c": i % SPRITE["cols"], "r": i // SPRITE["cols"]}
    for c in candidates:
        if isinstance(c["img"], str):
            c["img"] = None

    spots = []
    for s in read_csv(SPOTS_CSV):
        pos = parse_coords(s.get("koordinater"))
        if pos:
            spots.append({"xy": list(project(*pos)), "status": s.get("status", "")})
    data = {"proj": PROJ, "sprite": SPRITE, "outline": outline_path(), "candidates": candidates, "spots": spots}
    (OUT / "kandidater.json").write_text(json.dumps(data, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    print(f"{len(candidates)} kandidater, {len(spots)} spots → {OUT.relative_to(ROOT)}"
          + (f" · {len(missing)} mangler billede (kør review.py render --ren): {' '.join(missing[:8])}" if missing else ""))


if __name__ == "__main__":
    main()
