#!/usr/bin/env python3
"""Gennemgang af kandidat-kartoteket.

    python3 tools/kandidater/review.py next [-n 20] [--bbox S,V,N,Ø] [--min-score 2]
    python3 tools/kandidater/review.py render ID [ID ...] [--z 18]
    python3 tools/kandidater/review.py sheet ID ID ID ID          # 6 nærbilleder på ét kontaktark
    python3 tools/kandidater/review.py set ID --vurdering lovende --type flydebro --px 812,340 --begrundelse "…"
    python3 tools/kandidater/review.py apply vurderinger.jsonl
    python3 tools/kandidater/review.py promote ID --navn "Fussing Sø" [--status "Ikke testet"] [--start Dock]
    python3 tools/kandidater/review.py status

render tager et skærmbillede (1200×700) med headless Chrome: til venstre oversigt, til højre
nærbillede med rutenet. --px er en pixel i det billede (fx broens yderste ende) og omregnes
til koordinater ud fra det seneste skærmbillede af stedet.
Alle ændringer skrives i data/kandidater-log.csv.
"""
import argparse
import functools
import http.server
import json
import math
import os
import subprocess
import sys
import threading
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from kartotek import (ROOT, VAND, VURDERINGER, catalog_lock, fmt_coords, log, parse_coords, read_catalog, today,  # noqa: E402
                      write_catalog)

SCREENS = Path(__file__).resolve().parent / ".screens"
TYPES = ["flydebro", "ponton", "badebro", "bro", "slæbested", "strand", "andet"]
DETAIL_CENTER = (800, 350)  # midten af nærbilledet i skærmbilledet


def px_to_coords(center, zoom, x, y):
    """Web Mercator: pixel i skærmbilledet → (lat, lng)."""
    scale = 256 * 2 ** zoom
    siny = math.sin(math.radians(center[0]))
    cx = (center[1] + 180) / 360 * scale
    cy = (0.5 - math.log((1 + siny) / (1 - siny)) / (4 * math.pi)) * scale
    wx, wy = cx + (x - DETAIL_CENTER[0]), cy + (y - DETAIL_CENTER[1])
    lat = math.degrees(math.atan(math.sinh(math.pi - 2 * math.pi * wy / scale)))
    return lat, wx / scale * 360 - 180


def site_center(site):
    return parse_coords(site["koordinater"]) or parse_coords(site["auto_koordinater"])


# ---------- next / status ----------

def cmd_next(args, catalog):
    bbox = [float(v) for v in args.bbox.split(",")] if args.bbox else None
    todo = []
    for s in catalog:
        if s["vurdering"] or s["osm_status"] == "forsvundet" or float(s["score"] or 0) < args.min_score:
            continue
        p = site_center(s)
        if bbox and not (bbox[0] <= p[0] <= bbox[2] and bbox[1] <= p[1] <= bbox[3]):
            continue
        todo.append(s)
    for s in todo[: args.n]:
        print(f"{s['id']:<16} {s['score']:>4}  {s['kategorier']:<34} {s['navn'][:34]:<34} {s['område']}")
    print(f"– {len(todo)} ikke vurderede steder i udvalget")


def cmd_status(args, catalog):
    counts, types = {}, {}
    for s in catalog:
        key = s["vurdering"] or "ikke vurderet"
        counts[key] = counts.get(key, 0) + 1
        if s["type"]:
            types[s["type"]] = types.get(s["type"], 0) + 1
    print(f"{len(catalog)} steder i kartoteket")
    for k in ["lovende", "måske", "nej", "på kortet", "ikke vurderet"]:
        if k in counts:
            print(f"  {k:<14} {counts[k]}")
    if types:
        print("Typer: " + ", ".join(f"{k} {v}" for k, v in sorted(types.items(), key=lambda kv: -kv[1])))


# ---------- render ----------

def serve():
    class Quiet(http.server.SimpleHTTPRequestHandler):
        def log_message(self, *args):
            pass

    handler = functools.partial(Quiet, directory=str(ROOT))
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server


def cmd_render(args, catalog):
    by_id = {s["id"]: s for s in catalog}
    missing = [i for i in args.ids if i not in by_id]
    if missing:
        sys.exit(f"Ukendte id'er: {' '.join(missing)}")
    out_dir = SCREENS / "ren" if args.ren else SCREENS
    out_dir.mkdir(parents=True, exist_ok=True)
    server = serve()
    port = server.server_address[1]
    jobs = []
    for sid in args.ids:
        center = parse_coords(args.c) if args.c else site_center(by_id[sid])
        c = f"{center[0]:.7f},{center[1]:.7f}"
        jobs.append({"url": f"http://127.0.0.1:{port}/tools/kandidater/review.html?id={sid}&z={args.z}&c={c}"
                            + ("&ren=1" if args.ren else ""),
                     "out": str(out_dir / f"{sid}.png")})
        if not args.ren:  # --px regner ud fra det seneste gennemgangsbillede
            (SCREENS / f"{sid}.json").write_text(json.dumps({"center": center, "zoom": args.z}))
    jobs_file = SCREENS / f"jobs-{os.getpid()}.json"
    jobs_file.write_text(json.dumps(jobs))
    subprocess.run(["node", str(Path(__file__).resolve().parent / "shoot.mjs"), str(jobs_file)], check=True)
    jobs_file.unlink(missing_ok=True)
    server.shutdown()
    if args.ren:  # JPEG, så godkendelsessiden kan hente dem hurtigt
        for job in jobs:
            png = Path(job["out"])
            if png.exists():
                subprocess.run(["sips", "-s", "format", "jpeg", "-s", "formatOptions", "70", str(png),
                                "--out", str(png.with_suffix(".jpg"))], capture_output=True)
                png.unlink()


def cmd_sheet(args, catalog):
    """Samler op til 6 eksisterende skærmbilleder (halv størrelse) på ét billede."""
    if len(args.ids) > 6:
        sys.exit("Højst 6 id'er pr. kontaktark")
    missing = [i for i in args.ids if not (SCREENS / f"{i}.png").exists()]
    if missing:
        sys.exit(f"Kør render først for: {' '.join(missing)}")
    server = serve()
    port = server.server_address[1]
    out = SCREENS / f"ark-{'-'.join(args.ids)[:120]}.png"
    jobs_file = SCREENS / f"jobs-{os.getpid()}.json"
    jobs_file.write_text(json.dumps([{"url": f"http://127.0.0.1:{port}/tools/kandidater/sheet.html?ids={','.join(args.ids)}",
                                      "out": str(out)}]))
    subprocess.run(["node", str(Path(__file__).resolve().parent / "shoot.mjs"), str(jobs_file)], check=True)
    jobs_file.unlink(missing_ok=True)
    server.shutdown()


# ---------- promote ----------

def cmd_promote(args, catalog):
    """Flytter et sted fra kartoteket over på kortet (data/spots.csv) som et nyt spot."""
    import csv
    from kartotek import SPOTS_CSV, read_csv
    by_id = {s["id"]: s for s in catalog}
    site = by_id.get(args.id) or sys.exit(f"Ukendt id: {args.id}")
    config = json.loads((ROOT / "config.json").read_text(encoding="utf-8"))
    rows = read_csv(SPOTS_CSV)
    fields = list(rows[0].keys())
    navn = args.navn or site["navn"] or sys.exit("Stedet har intet navn i OSM – angiv --navn")
    slug = navn.lower().replace("æ", "ae").replace("ø", "oe").replace("å", "aa")
    base = "-".join("".join(c if c.isalnum() else " " for c in slug).split()) or "spot"
    ids = {r["id"] for r in rows}
    sid, i = base, 2
    while sid in ids:
        sid, i = f"{base}-{i}", i + 1
    start = args.start or {"flydebro": "Dock", "ponton": "Dock", "badebro": "Dock", "bro": "Dock",
                           "slæbested": "Andet", "strand": "Beach"}.get(site["type"], "Dock")
    spot = {f: "" for f in fields}
    spot.update({
        "id": sid, "vis": "TRUE", "navn": navn, "status": args.status, "start": start,
        "koordinater": site["koordinater"] or site["auto_koordinater"],
        "beskrivelse": f"Andre Bemærkninger:\n{site['begrundelse']}\nFundet via luftfoto – ikke testet." if site["begrundelse"] else "",
        "opdateret": today(), "note": f"Fra kandidat-kartoteket ({site['id']})",
    })
    if config.get("sheet_csv_url"):
        # Regnearket er kilden – skriv rækken ud, så den kan indsættes der i stedet.
        print("Regnearket er sat op. Indsæt denne række i fanen Spots:")
        print("\t".join(spot[f] for f in fields))
    else:
        with open(SPOTS_CSV, "a", newline="", encoding="utf-8") as f:
            csv.DictWriter(f, fieldnames=fields).writerow(spot)
        print(f"Tilføjet til {SPOTS_CSV.relative_to(ROOT)} som '{sid}' ({args.status}, {start})")
    old = site["vurdering"]
    site["vurdering"], site["tæt_på_spot"], site["vurderet"] = "på kortet", sid, today()
    log("sat vurdering", site["id"], old, "på kortet", f"promote → spot {sid}")
    write_catalog(catalog)


# ---------- set / apply ----------

def apply_decision(catalog, d):
    by_id = {s["id"]: s for s in catalog}
    site = by_id.get(d["id"])
    if not site:
        raise SystemExit(f"Ukendt id: {d['id']}")
    if d.get("vurdering") and d["vurdering"] not in VURDERINGER:
        raise SystemExit(f"{d['id']}: vurdering skal være en af {', '.join(VURDERINGER)}")
    if d.get("vand") and d["vand"] not in VAND:
        raise SystemExit(f"{d['id']}: vand skal være en af {', '.join(VAND)}")
    if d.get("type") and d["type"] not in TYPES:
        raise SystemExit(f"{d['id']}: type skal være en af {', '.join(TYPES)}")
    if d.get("px"):
        meta = SCREENS / f"{site['id']}.json"
        if not meta.exists():
            raise SystemExit(f"{d['id']}: --px kræver et skærmbillede (kør render først)")
        view = json.loads(meta.read_text())
        x, y = d["px"] if isinstance(d["px"], list) else map(float, str(d["px"]).split(","))
        d["koordinater"] = fmt_coords(px_to_coords(view["center"], view["zoom"], float(x), float(y)))
    changes = []
    for field in ("vurdering", "type", "koordinater", "begrundelse", "vand", "vand_note"):
        if d.get(field) is not None and d[field] != site[field]:
            changes.append((field, site[field], d[field]))
            site[field] = d[field]
    if any(f in ("vand", "vand_note") for f, _, _ in changes):
        site["vand_tjekket"] = today()
    if any(f not in ("vand", "vand_note") for f, _, _ in changes):
        site["vurderet"] = today()
        for field, old, new in changes:
            log(f"sat {field}", site["id"], old, new, d.get("note", ""))
    return site, changes


def cmd_set(args, catalog):
    d = {"id": args.id, "vurdering": args.vurdering, "type": args.type, "px": args.px,
         "koordinater": args.koordinater, "begrundelse": args.begrundelse}
    site, changes = apply_decision(catalog, d)
    write_catalog(catalog)
    print(f"{site['id']}: {site['vurdering']} · {site['type']} · {site['koordinater']} · {len(changes)} ændring(er)")


def cmd_apply(args, catalog):
    n = 0
    for line in Path(args.file).read_text(encoding="utf-8").splitlines():
        if line.strip():
            site, changes = apply_decision(catalog, json.loads(line))
            n += 1
            print(f"{site['id']:<16} {site['vurdering']:<9} {site['type']:<10} {site['koordinater']}")
    write_catalog(catalog)
    print(f"{n} vurderinger gemt")


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)
    n = sub.add_parser("next")
    n.add_argument("-n", type=int, default=20)
    n.add_argument("--bbox", help="syd,vest,nord,øst")
    n.add_argument("--min-score", type=float, default=0)
    sub.add_parser("status")
    r = sub.add_parser("render")
    r.add_argument("ids", nargs="+")
    r.add_argument("--z", type=int, default=18)
    r.add_argument("--c", help="centrér et andet sted: 'lat, lng'")
    r.add_argument("--ren", action="store_true", help="rent billede til godkendelsessiden (JPEG i .screens/ren/)")
    sh = sub.add_parser("sheet")
    sh.add_argument("ids", nargs="+")
    s = sub.add_parser("set")
    s.add_argument("id")
    s.add_argument("--vurdering", choices=list(VURDERINGER))
    s.add_argument("--type", choices=TYPES)
    s.add_argument("--px", help="x,y i seneste skærmbillede")
    s.add_argument("--koordinater")
    s.add_argument("--begrundelse")
    pr = sub.add_parser("promote")
    pr.add_argument("id")
    pr.add_argument("--navn")
    pr.add_argument("--status", default="Ikke testet", choices=["Virker", "Ikke testet", "Virker ikke"])
    pr.add_argument("--start", choices=["Dock", "Rock", "Jump", "Beach", "Andet"])
    a = sub.add_parser("apply")
    a.add_argument("file")
    args = p.parse_args()
    if args.cmd in ("set", "apply", "promote"):
        with catalog_lock():
            catalog = read_catalog()
            {"set": cmd_set, "apply": cmd_apply, "promote": cmd_promote}[args.cmd](args, catalog)
        return
    catalog = read_catalog()
    {"next": cmd_next, "status": cmd_status, "render": cmd_render, "sheet": cmd_sheet, "promote": cmd_promote, "set": cmd_set, "apply": cmd_apply}[args.cmd](args, catalog)


if __name__ == "__main__":
    main()
